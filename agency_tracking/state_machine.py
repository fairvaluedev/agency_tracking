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
		("Registered", "Cancelled"),
		("CV Generated", "Cancelled"),
		# entry_track-forced regression (applicant_api.update_applicant) and Cancelled->restart
		# (applicant_api.restart_applicant) both land here -- Draft->Cancelled is deliberately
		# NOT an edge (Cancelled only applies once something is committed, Registered onward).
		("Registered", "Draft"),
		("CV Generated", "Draft"),
		("Cancelled", "Draft"),
		("Cancelled", "Registered"),
	},
	"Placement": {
		("Selected", "Processing"),
		("Processing", "Stamped"),
		("Stamped", "Ticketed"),
		("Ticketed", "Departed"),
		# Cancellable from any pre-Departed stage (applicant_api.cancel_applicant cascades
		# here) -- Departed stays terminal/uncancellable.
		("Selected", "Cancelled"),
		("Processing", "Cancelled"),
		("Stamped", "Cancelled"),
		("Ticketed", "Cancelled"),
	},
	"Applicant Transaction": {
		("Pending", "Approved"),
		("Pending", "Rejected"),
		("Approved", "Voided"),
	},
	"Complaint": {
		("New", "Unresolved"),
		("Unresolved", "Resolved"),
		("Unresolved", "Returned - Free Replacement Required"),
		("Unresolved", "Escalated"),
		("Unresolved", "Dismissed"),
	},
}

# (from_status, to_status) -> callable(doc) -> bool. Applicant's Draft->Registered move has no
# cross-doctype gate (just the field-floor/medical check already in Applicant.validate()).
# Registered->CV Generated is gated on cv_generation_gate (Standard track only, Step 2).
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


def transition(doc, new_status, actor=None, override=False, override_reason=None, remarks=None):
	"""The only sanctioned status-change path. Validates the move is a legal edge for this
	doctype, runs any registered gate, commits the change (which re-triggers the doctype's
	own validate() against the new status), logs a Process Event, and returns the saved doc.

	Manager Override (business-workflow-srs.md: "can override a blocked step... always with a
	written reason"): if a gate blocks the move, override=True + a non-empty override_reason
	lets a Manager/Admin force it through anyway. Override only ever bypasses a *gate* — the
	ALLOWED_TRANSITIONS topology itself is never overridable; there's no business case in the
	spec for skipping an entire lifecycle stage, only for forcing past a blocked condition
	within an otherwise-legal move.

	remarks: recorded on the Process Event same as override_reason, but for plain (non-gated)
	transitions that still want a reason on the audit trail -- e.g. cancel_applicant's written
	cancellation reason, which isn't an override of anything.
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
			"remarks": override_reason if is_override else remarks,
		}
	).insert(ignore_permissions=True)

	side_effect = TRANSITION_SIDE_EFFECTS.get((doc.doctype, new_status))
	if side_effect:
		try:
			side_effect(doc, current_status)
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


def cv_generation_gate(applicant) -> bool:
	"""Registered -> CV Generated (Part A.2 Stage 3): Standard track only.

	2026-08-29: the Musaned gate (blocking CV generation for Saudi-bound Standard candidates
	until musaned_status == ALTEYAZECHEM) and the musaned_status field itself have both been
	removed per direct instruction -- Musaned tracking is no longer part of this system at all.
	"""
	return applicant.entry_track == "Standard"


STAGE_GATES[("Registered", "CV Generated")] = cv_generation_gate


# --- Medical 2 gate (Part A.2 Stage 8 / Step 6) ---
# The pre-departure check (~72h before flight) is separate from the earlier registration-time
# FIT check — a candidate can pass the first medical, get all the way to Ticketed, and still
# fail this one. "If this fails, the flight is cancelled and departure is blocked."


def medical_2_gate(placement) -> bool:
	return placement.medical_2_status == "FIT"


STAGE_GATES[("Ticketed", "Departed")] = medical_2_gate


# --- Post-contract medical gate (2026-08-29, new) ---
# A fresh checkpoint right after contract upload/Placement creation, distinct from both the
# Applicant's earlier registration-time FIT check and the pre-departure Medical 2 check above.
# UNFIT here doesn't just block the gate -- it cancels the whole Applicant + Placement (see
# applicant_api.cancel_applicant, called by placement_api.record_selected_medical_result).
# Applies uniformly to Standard (Saudi/Kuwait) and Muayena.


def medical_selected_gate(placement) -> bool:
	return placement.medical_selected_status == "FIT"


STAGE_GATES[("Selected", "Processing")] = medical_selected_gate


# --- All-mandatory-clearance-steps-complete gate (Part A.2 Stage 6 / Step 7) ---
# "Stamped — all mandatory corridor steps issued." Optional steps (is_mandatory=0) don't block.


CLEARANCE_STEP_DONE_STATUSES = {"Complete", "Issued", "Stamped"}


def all_mandatory_clearance_steps_complete(placement) -> bool:
	steps = frappe.get_all(
		"Clearance Step",
		filters={"placement": placement.name, "is_mandatory": 1},
		fields=["status"],
	)
	return bool(steps) and all(s.status in CLEARANCE_STEP_DONE_STATUSES for s in steps)


STAGE_GATES[("Processing", "Stamped")] = all_mandatory_clearance_steps_complete


# --- Free-replacement window gate (Part A.4 / Step 10) ---
# "A 3-month window from departure, during which a returned worker triggers a free replacement
# obligation." Measured from Placement.departed_on (stamped once, on first entry to Departed —
# see Placement.stamp_departed_on), not the complaint's own creation date.

FREE_REPLACEMENT_WINDOW_DAYS = 90


def within_free_replacement_window(complaint) -> bool:
	placement = frappe.get_doc("Placement", complaint.placement)
	if not placement.departed_on:
		return False
	days_since_departure = (frappe.utils.now_datetime() - placement.departed_on).days
	return days_since_departure <= FREE_REPLACEMENT_WINDOW_DAYS


STAGE_GATES[("Unresolved", "Returned - Free Replacement Required")] = within_free_replacement_window


# --- Applicant cycle_number bump (2026-08-29 lifecycle spec) ---
# "Increments if and only if the status transition lands specifically on Draft or Registered,
# coming from an already-completed state (Registered, CV Generated, or Cancelled)." Covers both
# trigger paths uniformly -- entry_track-forced regression (applicant_api.update_applicant) and
# Cancelled->restart (applicant_api.restart_applicant) -- since both just call transition() and
# land here. A plain edit that never changes status never touches this at all.

CYCLE_BUMP_FROM_STATUSES = {"Registered", "CV Generated", "Cancelled"}


def bump_cycle_number(applicant, from_status):
	if from_status in CYCLE_BUMP_FROM_STATUSES:
		frappe.db.set_value(
			"Applicant", applicant.name, "cycle_number", (applicant.cycle_number or 1) + 1
		)


TRANSITION_SIDE_EFFECTS[("Applicant", "Draft")] = bump_cycle_number
TRANSITION_SIDE_EFFECTS[("Applicant", "Registered")] = bump_cycle_number
