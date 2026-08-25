# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure. Foreign Agency
# users get NO direct doctype permissions on Applicant/Placement/Contractor (see the doctype
# JSONs) — every bit of portal access is mediated here, with its own explicit role/ownership
# checks, per Part G ("Foreign Agency (portal): Own country's catalog, own placements...").

import frappe

from agency_tracking.state_machine import lock_applicant_row

# Non-PII browsing fields only (business names/skills, not passport/national ID/phone/address/
# emergency contacts) — the spec doesn't enumerate an exact portal field list, so this is a
# judgment call; tightened rather than loosened since the alternative is leaking PII to a
# third-party agency before any commission has even been agreed.
PORTAL_FIELDS = [
	"name",
	"full_name",
	"gender",
	"nationality",
	"date_of_birth",
	"target_job",
	"education",
	"photograph",
]


def _get_contractor_for_session_user():
	if "Foreign Agency" not in frappe.get_roles():
		frappe.throw("Not permitted.", frappe.PermissionError)
	contractor_name = frappe.db.get_value("Contractor", {"user": frappe.session.user}, "name")
	if not contractor_name:
		frappe.throw("No Contractor record is linked to this user.", frappe.PermissionError)
	return frappe.get_doc("Contractor", contractor_name)


def _get_latest_cv_record(applicant_name):
	return frappe.db.get_value(
		"CV Record",
		{"applicant": applicant_name, "docstatus": 1},
		"name",
		order_by="creation desc",
	)


@frappe.whitelist()
def list_portal_candidates():
	"""Part G: an agency sees only its own destination country's catalog — Standard-track
	candidates that are CV Generated and not yet locked by anyone (active_placement empty)."""
	contractor = _get_contractor_for_session_user()
	return frappe.get_all(
		"Applicant",
		filters={
			"entry_track": "Standard",
			"status": "CV Generated",
			"active_placement": ["is", "not set"],
			"destination_country": contractor.country,
		},
		fields=PORTAL_FIELDS,
		ignore_permissions=True,
	)


@frappe.whitelist()
def select_candidate(applicant_name):
	"""Part A.2 Stage 4: atomic, globally exclusive selection. The instant one agency selects
	a candidate, they vanish from every other agency's view — enforced here with a row lock
	(SELECT ... FOR UPDATE) so two concurrent selections can't both see the candidate as free.
	"""
	contractor = _get_contractor_for_session_user()

	applicant = frappe.get_doc("Applicant", applicant_name)
	if applicant.entry_track != "Standard":
		frappe.throw("Only Standard-track candidates are selected via the portal.", frappe.ValidationError)
	if applicant.status != "CV Generated":
		frappe.throw(
			f"{applicant_name} is not currently portal-visible (status: {applicant.status}).",
			frappe.ValidationError,
		)
	if applicant.destination_country != contractor.country:
		frappe.throw("Not permitted.", frappe.PermissionError)

	# Row lock held until this request's transaction commits — a second, concurrent
	# select_candidate() for the same applicant blocks here until the first is done, then
	# sees active_placement already set and is rejected. Without this, two agencies could
	# both read active_placement as empty before either had written it.
	lock_applicant_row(applicant_name)
	current_lock = frappe.db.get_value("Applicant", applicant_name, "active_placement")
	if current_lock:
		frappe.throw(
			f"{applicant_name} has already been selected by another agency.", frappe.ValidationError
		)

	placement = frappe.get_doc(
		{
			"doctype": "Placement",
			"applicant": applicant_name,
			"contractor": contractor.name,
			"destination_country": applicant.destination_country,
			"status": "Selected",
			"cv_record": _get_latest_cv_record(applicant_name),
		}
	).insert(ignore_permissions=True)

	frappe.db.set_value("Applicant", applicant_name, "active_placement", placement.name)
	return placement.as_dict()
