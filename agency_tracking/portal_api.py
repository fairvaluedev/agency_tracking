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


def _get_contractor_for_session_user(contractor_override=None):
	if contractor_override:
		return frappe.get_doc("Contractor", contractor_override)
	if "Foreign Agency" in frappe.get_roles():
		contractor_name = frappe.db.get_value("Contractor", {"user": frappe.session.user}, "name")
		if contractor_name:
			return frappe.get_doc("Contractor", contractor_name)
	if frappe.session.user == "Administrator" or ({"Manager", "Admin", "System Manager"} & set(frappe.get_roles())):
		first = frappe.db.get_value("Contractor", {}, "name")
		if first:
			return frappe.get_doc("Contractor", first)
		frappe.throw("No Contractor record found in system.", frappe.ValidationError)
	frappe.throw("Not permitted.", frappe.PermissionError)


def _get_latest_cv_record(applicant_name):
	return frappe.db.get_value(
		"CV Record",
		{"applicant": applicant_name, "docstatus": 1},
		"name",
		order_by="creation desc",
	)


@frappe.whitelist()
def list_portal_candidates(target_job=None, gender=None, **kwargs):
	"""business-workflow-srs.md: "Contractors can browse available registered candidates (CV
	status), filtered by their quota country." Only CV Generated candidates (Part A.2 Stage 4);
	only the contractor's own country."""
	allowed_roles = {"Foreign Agency", "Manager", "Admin", "System Manager", "Registrar"}
	if frappe.session.user != "Administrator" and not (allowed_roles & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	filters = {
		"status": "CV Generated",
		"entry_track": "Standard",
	}
	if "Foreign Agency" in frappe.get_roles():
		contractor = _get_contractor_for_session_user()
		filters["destination_country"] = contractor.country
	if target_job:
		filters["target_job"] = target_job
	if gender:
		filters["gender"] = gender

	return frappe.get_list(
		"Applicant",
		filters=filters,
		fields=PORTAL_FIELDS,
		ignore_permissions=True,
	)


@frappe.whitelist()
def select_candidate(applicant_name=None, free_replacement_for_complaint=None, contractor_name=None, **kwargs):
	"""Part A.2 Stage 4: atomic, globally exclusive selection. The instant one agency selects
	a candidate, they vanish from every other agency's view — enforced here with a row lock
	(SELECT ... FOR UPDATE) so two concurrent selections can't both see the candidate as free.
	"""
	applicant_name = applicant_name or kwargs.get("applicant")
	contractor_name = contractor_name or kwargs.get("contractor")
	if not applicant_name:
		frappe.throw("applicant_name is required.", frappe.ValidationError)

	contractor = _get_contractor_for_session_user(contractor_override=contractor_name)

	applicant = frappe.get_doc("Applicant", applicant_name)
	if applicant.active_placement:
		return frappe.get_doc("Placement", applicant.active_placement).as_dict()
	if applicant.entry_track != "Standard":
		frappe.throw("Only Standard-track candidates are selected via the portal.", frappe.ValidationError)
	if applicant.status != "CV Generated":
		frappe.throw(
			f"{applicant_name} is not currently portal-visible (status: {applicant.status}).",
			frappe.ValidationError,
		)
	if applicant.destination_country != contractor.country and frappe.session.user != "Administrator" and not ({"Manager", "Admin", "System Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)

	if free_replacement_for_complaint:
		complaint = frappe.get_doc("Complaint", free_replacement_for_complaint)
		if complaint.status != "Returned - Free Replacement Required":
			frappe.throw(
				f"{free_replacement_for_complaint} is not an approved free-replacement complaint "
				f"(status: {complaint.status}).",
				frappe.ValidationError,
			)
		if complaint.contractor != contractor.name:
			frappe.throw("Not permitted.", frappe.PermissionError)
		if frappe.db.exists("Placement", {"free_replacement_for_complaint": free_replacement_for_complaint}):
			frappe.throw(
				f"{free_replacement_for_complaint}'s free replacement has already been used.",
				frappe.ValidationError,
			)

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
			"is_free_replacement": 1 if free_replacement_for_complaint else 0,
			"free_replacement_for_complaint": free_replacement_for_complaint,
		}
	).insert(ignore_permissions=True)

	frappe.db.set_value("Applicant", applicant_name, "active_placement", placement.name)
	return placement.as_dict()


@frappe.whitelist()
def list_my_wakala_requests():
	"""New (2026-08-29): a Contractor-scoped list of every unpaid Wakala-bearing Embassy step
	for their own placements — the page the watchdog/manual reminders (watchdogs.
	wakala_reminder_watchdog) are actually pointing them at. Mirrors list_my_clearance_steps()'s
	pattern for the internal-staff side."""
	contractor = _get_contractor_for_session_user()
	placement_names = frappe.get_all("Placement", filters={"contractor": contractor.name}, pluck="name")
	if not placement_names:
		return []
	return frappe.get_all(
		"Clearance Step",
		filters={
			"placement": ["in", placement_names],
			"step_type": "Embassy",
			"wakala_status": ["!=", "Paid"],
		},
		fields=["name", "placement", "wakala_amount", "wakala_status", "status"],
		ignore_permissions=True,
	)
