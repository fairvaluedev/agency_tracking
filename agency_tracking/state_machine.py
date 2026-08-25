# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part C of master-build-specification.md: two enforcement points.
#   validate()   — is the data allowed to exist in this state? (lives on each doctype)
#   transition() — is this process move allowed right now? (lives here, shared)
#
# Built starting Step 1 (not deferred to Step 6 as Part I's sequence might suggest) because
# CLAUDE.md's rule is absolute: no doc.status = X; doc.save() anywhere, ever. Only the contents
# of ALLOWED_TRANSITIONS and STAGE_GATES grow as later build steps add doctypes/stages — the
# function itself never changes shape. See BUILD_LOG.md "Standing decisions".

import frappe


def lock_applicant_row(applicant_name):
	"""Row-level lock (SELECT ... FOR UPDATE), held until the current request's transaction
	commits. Used anywhere two concurrent requests could both read active_placement as empty
	before either writes it — portal selection (Step 3) and Muayena direct-entry (Step 4)."""
	frappe.db.sql("SELECT `name` FROM `tabApplicant` WHERE `name`=%s FOR UPDATE", applicant_name)


# doctype -> set of (from_status, to_status) edges that are legal to attempt.
# Extended as each build step introduces new statuses (Placement's Selected/Processing/
# Stamped/Ticketed/Departed land here from Step 3 onward).
ALLOWED_TRANSITIONS = {
	"Applicant": {
		("Draft", "Registered"),
		("Registered", "CV Generated"),
	},
	"Placement": {
		("Selected", "Processing"),
		("Processing", "Stamped"),
		("Stamped", "Ticketed"),
		("Ticketed", "Departed"),
	},
}

# (from_status, to_status) -> callable(doc) -> bool. Applicant's Draft->Registered move has no
# cross-doctype gate (just the field-floor/medical check already in Applicant.validate()).
# Registered->CV Generated is gated on cv_generation_gate (Standard track + Musaned, Step 2).
# Placement's Ticketed->Departed is gated on medical_2_gate (Step 6). Processing->Stamped is
# gated on all_mandatory_clearance_steps_complete (Step 7, below). Selected->Processing and
# Stamped->Ticketed have no gate — nothing to check against for either.
STAGE_GATES = {}

# (doctype, to_status) -> callable(doc). Runs once, after a transition has already committed
# (doc.save() + Process Event logged) — orchestration, not validation; a side effect here
# can't block the move itself (that's what STAGE_GATES is for). Keeps transition() the single
# place that drives cross-doctype consequences (Part C: "triggers reopen_for_reprocessing()...
# triggers commission accrual on reaching Departed") instead of scattering them across callers.
TRANSITION_SIDE_EFFECTS = {}


def transition(doc, new_status, actor=None, override=False, override_reason=None):
	"""The only sanctioned status-change path. Validates the move is a legal edge for this
	doctype, runs any registered gate, commits the change (which re-triggers the doctype's
	own validate() against the new status), logs a Process Event, and returns the saved doc.

	Manager Override (business-workflow-srs.md: "can override a blocked step... always with a
	written reason"): if a gate blocks the move, override=True + a non-empty override_reason
	lets a Manager/Admin force it through anyway. Override only ever bypasses a *gate* — the
	ALLOWED_TRANSITIONS topology itself is never overridable; there's no business case in the
	spec for skipping an entire lifecycle stage, only for forcing past a blocked condition
	within an otherwise-legal move.
	"""
	current_status = doc.status
	allowed = ALLOWED_TRANSITIONS.get(doc.doctype, set())
	if (current_status, new_status) not in allowed:
		frappe.throw(
			"Cannot move {0} {1} from '{2}' to '{3}'.".format(
				doc.doctype, doc.name, current_status, new_status
			),
			frappe.ValidationError,
		)

	gate = STAGE_GATES.get((current_status, new_status))
	gate_passed = gate(doc) if gate else True
	is_override = bool(gate) and not gate_passed

	if is_override:
		if not override:
			frappe.throw(
				"'{0}' -> '{1}' is blocked: gate condition not met.".format(current_status, new_status),
				frappe.ValidationError,
			)
		if not ({"Manager", "Admin"} & set(frappe.get_roles())):
			frappe.throw("Only Manager or Admin can override a blocked transition.", frappe.PermissionError)
		if not override_reason:
			frappe.throw("A written reason is required to override this gate.", frappe.ValidationError)

	actor = actor or frappe.session.user
	doc.status = new_status
	doc.save()

	frappe.get_doc(
		{
			"doctype": "Process Event",
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"event_type": "Override" if is_override else "Transition",
			"from_status": current_status,
			"to_status": new_status,
			"actor": actor,
			"remarks": override_reason if is_override else None,
		}
	).insert(ignore_permissions=True)

	side_effect = TRANSITION_SIDE_EFFECTS.get((doc.doctype, new_status))
	if side_effect:
		try:
			side_effect(doc)
		except Exception:
			# Side effects run after the transition has already committed (doc.save() +
			# Process Event, both above). Letting an exception here propagate would make
			# transition() look like it failed to the caller while the status change actually
			# went through — corrupting the "only sanctioned path" guarantee (a caller who
			# catches the exception and retries, or assumes nothing happened, would be wrong).
			# Side effects are best-effort automation layered on top of a transition that has
			# already legitimately happened; only STAGE_GATES may block a transition itself.
			# Real failures (e.g. commission accrual missing a configured rate) are logged for
			# staff to notice and resolve manually, not silently lost.
			frappe.log_error(
				title="Transition side effect failed",
				message=f"{doc.doctype} {doc.name}: {current_status} -> {new_status}",
			)

	return doc


# --- Musaned gate (Part A.2) ---
# Wired into CV generation (Step 2): registered in STAGE_GATES below, and CV Record.validate()
# also checks it directly for a clearer, CV-specific error message.

MUSANED_APPROVED_STATUS = "ALTEYAZECHEM"
MUSANED_BLOCKED_STATUS = "TEYZALECH"


def musaned_gate_passed(applicant) -> bool:
	"""Saudi-bound Standard candidates cannot proceed to CV generation until Musaned status
	is ALTEYAZECHEM. Not applicable to Kuwait or to Muayena candidates (they skip CV/portal
	entirely per Part A.1).
	"""
	if applicant.entry_track != "Standard":
		return True
	if applicant.destination_country != "Saudi Arabia":
		return True
	return applicant.musaned_status == MUSANED_APPROVED_STATUS


def cv_generation_gate(applicant) -> bool:
	"""Registered -> CV Generated (Part A.2 Stage 3): Standard track only, and subject to
	the Musaned gate above."""
	if applicant.entry_track != "Standard":
		return False
	return musaned_gate_passed(applicant)


STAGE_GATES[("Registered", "CV Generated")] = cv_generation_gate


# --- Medical 2 gate (Part A.2 Stage 8 / Step 6) ---
# The pre-departure check (~72h before flight) is separate from the earlier registration-time
# FIT check — a candidate can pass the first medical, get all the way to Ticketed, and still
# fail this one. "If this fails, the flight is cancelled and departure is blocked."


def medical_2_gate(placement) -> bool:
	return placement.medical_2_status == "FIT"


STAGE_GATES[("Ticketed", "Departed")] = medical_2_gate


# --- All-mandatory-clearance-steps-complete gate (Part A.2 Stage 6 / Step 7) ---
# "Stamped — all mandatory corridor steps issued." Optional steps (is_mandatory=0) don't block.


def all_mandatory_clearance_steps_complete(placement) -> bool:
	steps = frappe.get_all(
		"Clearance Step",
		filters={"placement": placement.name, "is_mandatory": 1},
		fields=["status"],
	)
	return bool(steps) and all(s.status == "Complete" for s in steps)


STAGE_GATES[("Processing", "Stamped")] = all_mandatory_clearance_steps_complete
