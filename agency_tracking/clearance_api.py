# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe
from frappe.utils import today

from agency_tracking.clearance_engine import assign_clearance_step


def _is_assigned_officer(clearance_step_name):
	return bool(
		frappe.db.exists(
			"ToDo",
			{
				"reference_type": "Clearance Step",
				"reference_name": clearance_step_name,
				"allocated_to": frappe.session.user,
				"status": "Open",
			},
		)
	)


@frappe.whitelist()
def complete_clearance_step(clearance_step_name, reference_no=None, amount=None):
	"""Mark a Clearance Step complete. Only the officer currently ToDo-assigned to this exact
	row, or Manager/Admin, may do so — Part G's "per-row" scoping applies here too, not just
	to reads."""
	if not (_is_assigned_officer(clearance_step_name) or {"Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)

	step = frappe.get_doc("Clearance Step", clearance_step_name)
	step.status = "Complete"
	step.date_completed = today()
	step.completed_by = frappe.session.user
	if reference_no:
		step.reference_no = reference_no
	if amount is not None:
		step.amount = amount
		step.payment_status = "Paid"
	step.save(ignore_permissions=True)

	open_todos = frappe.get_all(
		"ToDo",
		filters={"reference_type": "Clearance Step", "reference_name": clearance_step_name, "status": "Open"},
		pluck="name",
	)
	for todo_name in open_todos:
		frappe.db.set_value("ToDo", todo_name, "status", "Closed")

	return step.as_dict()


@frappe.whitelist()
def start_clearance_step(clearance_step_name):
	if not (_is_assigned_officer(clearance_step_name) or {"Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	step = frappe.get_doc("Clearance Step", clearance_step_name)
	step.status = "In Progress"
	step.date_started = today()
	step.save(ignore_permissions=True)
	return step.as_dict()


@frappe.whitelist()
def reassign_clearance_step(clearance_step_name, new_officer):
	"""Part A.2: "reassignable by a manager if needed" — the escape hatch for the default
	auto-chain."""
	if not ({"Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	assign_clearance_step(clearance_step_name, new_officer)
	return {"clearance_step": clearance_step_name, "assigned_to": new_officer}


@frappe.whitelist()
def list_my_clearance_steps():
	"""A Clearance Officer / Ticketing-Dispatch user's own queue — driven entirely by the same
	ToDo-based permission scoping as direct doctype access (Clearance Step's
	get_permission_query_conditions), so this and a raw list call return the same rows."""
	return frappe.get_list(
		"Clearance Step",
		fields=["name", "placement", "step_type", "status", "sequence_order", "is_mandatory"],
		order_by="sequence_order asc",
	)
