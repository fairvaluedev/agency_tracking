# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe
from frappe.utils import today

from agency_tracking.state_machine import transition

INTERNAL_STAFF_ROLES = {
	"Recruitment/Intake",
	"Clearance Officer",
	"Ticketing/Dispatch",
	"Complaint Manager",
	"Finance Manager",
	"Manager",
	"Admin",
}

TERMINAL_STATUSES = {"Resolved", "Returned - Free Replacement Required", "Escalated", "Dismissed"}


@frappe.whitelist()
def create_complaint(placement, description, worker_status_at_complaint):
	"""business-workflow-srs.md Part 5: "Foreign agencies (or occasionally internal staff on
	their behalf) can log a complaint against any worker." An agency can only complain about
	their own placement; internal staff need some recognized staff role, but creation itself
	isn't restricted the way resolution is."""
	linked_contractor = frappe.db.get_value("Contractor", {"user": frappe.session.user}, "name")
	placement_doc = frappe.get_doc("Placement", placement)

	if linked_contractor:
		if linked_contractor != placement_doc.contractor:
			frappe.throw("Not permitted.", frappe.PermissionError)
		raised_by = "Foreign Agency"
	elif INTERNAL_STAFF_ROLES & set(frappe.get_roles()):
		raised_by = "Internal Staff"
	else:
		frappe.throw("Not permitted.", frappe.PermissionError)

	complaint = frappe.get_doc(
		{
			"doctype": "Complaint",
			"placement": placement,
			"contractor": placement_doc.contractor,
			"raised_by": raised_by,
			"worker_status_at_complaint": worker_status_at_complaint,
			"description": description,
			"status": "New",
		}
	).insert(ignore_permissions=True)
	return complaint.as_dict()


@frappe.whitelist()
def list_unresolved_complaints():
	"""business-workflow-srs.md Part 5: "sorted oldest-first so nothing quietly sits forgotten
	at the bottom of a list." """
	if not ({"Complaint Manager", "Admin", "Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	return frappe.get_list(
		"Complaint",
		filters={"status": "Unresolved"},
		fields=["name", "placement", "contractor", "description", "creation"],
		order_by="creation asc",
	)


@frappe.whitelist()
def acknowledge_complaint(complaint_name):
	"""New -> Unresolved."""
	if not ({"Complaint Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	complaint = frappe.get_doc("Complaint", complaint_name)
	transition(complaint, "Unresolved")
	return complaint.as_dict()


@frappe.whitelist()
def resolve_complaint(complaint_name, new_status, resolution_notes=None, override_reason=None):
	"""Master spec Part A.5: "Only Complaint Manager and Admin can move resolution status."
	Dismissed requires a written reason — enforced both here (clear error before the doctype
	validate() would also catch it) and in Complaint.validate() as a defense-in-depth backstop.

	override_reason (Manager Override, e.g. approving a free replacement outside the normal
	3-month window in an exceptional case): overriding a gate is a Manager-level power
	throughout this build (transition() itself enforces Manager/Admin for any override), so
	the permission check here widens to include plain Manager specifically for an override
	attempt — an ordinary (non-override) resolution move stays Complaint Manager/Admin only,
	per Part A.5's literal statement.
	"""
	allowed_roles = {"Complaint Manager", "Admin", "Manager"} if override_reason else {"Complaint Manager", "Admin"}
	if not (allowed_roles & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if new_status not in TERMINAL_STATUSES:
		frappe.throw(f"'{new_status}' is not a resolution outcome.", frappe.ValidationError)
	if new_status == "Dismissed" and not resolution_notes:
		frappe.throw("A written reason is required to dismiss a complaint.", frappe.ValidationError)

	complaint = frappe.get_doc("Complaint", complaint_name)
	complaint.resolution_notes = resolution_notes
	complaint.resolved_by = frappe.session.user
	complaint.resolved_on = today()
	transition(complaint, new_status, override=bool(override_reason), override_reason=override_reason)
	return complaint.as_dict()
