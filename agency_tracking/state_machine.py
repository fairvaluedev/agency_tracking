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
}

# (from_status, to_status) -> callable(doc) -> bool. Applicant's Draft->Registered move has no
# cross-doctype gate (just the field-floor/medical check already in Applicant.validate()).
# Registered->CV Generated is gated on cv_generation_gate (Standard track + Musaned, Step 2).
# Further gates (Te'shsir->Injaz on medical FIT, Ticketed->Departed on Medical 2, etc.) are
# added at Step 6 once those stages exist.
STAGE_GATES = {}


def transition(doc, new_status, actor=None):
	"""The only sanctioned status-change path. Validates the move is a legal edge for this
	doctype, runs any registered gate, commits the change (which re-triggers the doctype's
	own validate() against the new status), and returns the saved doc.
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
	if gate and not gate(doc):
		frappe.throw(
			"'{0}' -> '{1}' is blocked: gate condition not met.".format(current_status, new_status),
			frappe.ValidationError,
		)

	doc.status = new_status
	doc.save()
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
