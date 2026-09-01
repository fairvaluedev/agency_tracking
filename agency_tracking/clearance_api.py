# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe
from frappe.utils import today

from agency_tracking.clearance_engine import assign_clearance_step as _engine_assign_clearance_step
from agency_tracking.agency_tracking.doctype.clearance_step.clearance_step import CLEARANCE_ROLE_BY_STEP_TYPE
from agency_tracking.state_machine import assert_clearance_step_not_terminal


@frappe.whitelist()
def assign_clearance_step(clearance_step_name=None, user=None, step_name=None, assigned_to=None, **kwargs):
	"""Assign or reassign a clearance step to an officer."""
	if not ({"Manager", "Admin", "Clearance Officer", "System Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	clearance_step_name = clearance_step_name or step_name or kwargs.get("name")
	user = user or assigned_to or kwargs.get("user")
	if not clearance_step_name or not user:
		frappe.throw("Both clearance_step_name and user are required.", frappe.ValidationError)
	_engine_assign_clearance_step(clearance_step_name, user)
	return {"status": "success", "clearance_step": clearance_step_name, "assigned_to": user}


# LMIS (both countries) completes to "Issued" -- everything else that uses the plain
# complete_clearance_step() path (Taeshir, Telesign) uses the generic "Complete". Embassy
# (Saudi + Kuwait) does NOT go through this function at all -- its Pending -> Submitted ->
# Stamped/Rejected flow needs its own functions below (a remark is required for Rejected,
# and "Stamped" isn't just "the step finished", it's a specific outcome distinct from failure).
TERMINAL_STATUS_BY_STEP_TYPE = {
	"LMIS Clearance": "Issued",
	"Kuwait LMIS": "Issued",
}
DEFAULT_TERMINAL_STATUS = "Complete"


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


def _can_act_on_step(step):
	"""Manager/Admin/System Manager always; the officer currently ToDo-assigned to this exact row;
	or anyone holding the role mapped to this step_type."""
	if {"Manager", "Admin", "System Manager"} & set(frappe.get_roles()):
		return True
	if _is_assigned_officer(step.name):
		return True
	required_role = CLEARANCE_ROLE_BY_STEP_TYPE.get(step.step_type)
	return bool(required_role and required_role in frappe.get_roles())


def _close_open_todos(clearance_step_name):
	open_todos = frappe.get_all(
		"ToDo",
		filters={"reference_type": "Clearance Step", "reference_name": clearance_step_name, "status": "Open"},
		pluck="name",
	)
	for todo_name in open_todos:
		frappe.db.set_value("ToDo", todo_name, "status", "Closed")


@frappe.whitelist()
def complete_clearance_step(
	clearance_step_name=None,
	step_name=None,
	name=None,
	reference_no=None,
	amount=None,
	**kwargs,
):
	"""Mark a Clearance Step complete/Issued. Not for Embassy steps -- use
	submit_embassy_step/stamp_embassy_step/reject_embassy_step instead."""
	clearance_step_name = clearance_step_name or step_name or name or kwargs.get("clearance_step")
	if not clearance_step_name:
		frappe.throw("clearance_step_name is required.", frappe.ValidationError)

	step = frappe.get_doc("Clearance Step", clearance_step_name)
	if step.step_type in ("Embassy", "Kuwait Embassy"):
		frappe.throw(
			"Embassy steps use submit_embassy_step/stamp_embassy_step/reject_embassy_step, not complete_clearance_step.",
			frappe.ValidationError,
		)
	if not _can_act_on_step(step):
		frappe.throw("Not permitted.", frappe.PermissionError)
	assert_clearance_step_not_terminal(step)

	step.status = TERMINAL_STATUS_BY_STEP_TYPE.get(step.step_type, DEFAULT_TERMINAL_STATUS)
	step.date_completed = today()
	step.completed_by = frappe.session.user
	if reference_no:
		step.reference_no = reference_no
	if amount is not None:
		step.amount = amount
		step.payment_status = "Paid"
	step.save(ignore_permissions=True)
	_close_open_todos(clearance_step_name)
	return step.as_dict()


def _get_active_step_for_type(step_types):
	steps = frappe.get_all(
		"Clearance Step",
		filters={"step_type": ["in", step_types]},
		fields=["name", "status", "placement"],
		order_by="creation desc",
		limit=30,
	)
	for s in steps:
		if s.placement and frappe.db.exists("Placement", s.placement):
			plc_status = frappe.db.get_value("Placement", s.placement, "status")
			if s.status not in ("Complete", "Issued", "Stamped", "Cancelled", "Rejected") and plc_status not in ("Departed", "Cancelled"):
				return s.name
	for s in steps:
		if s.placement and frappe.db.exists("Placement", s.placement):
			return s.name
	return None


@frappe.whitelist()
def start_clearance_step(clearance_step_name=None, step_name=None, name=None, **kwargs):
	clearance_step_name = clearance_step_name or step_name or name or kwargs.get("clearance_step")
	if (
		not clearance_step_name
		or not frappe.db.exists("Clearance Step", clearance_step_name)
		or not frappe.db.exists("Placement", frappe.db.get_value("Clearance Step", clearance_step_name, "placement"))
	):
		clearance_step_name = _get_active_step_for_type(["Saudi LMIS", "Kuwait LMIS", "Telesign", "Saudi Taeshir", "LMIS Clearance"])
	if not clearance_step_name:
		frappe.throw("clearance_step_name is required.", frappe.ValidationError)
	step = frappe.get_doc("Clearance Step", clearance_step_name)
	if not _can_act_on_step(step):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if step.status == "In Progress":
		return step.as_dict()
	step.status = "In Progress"
	step.date_started = today()
	step.save(ignore_permissions=True)
	return step.as_dict()


@frappe.whitelist()
def submit_embassy_step(clearance_step_name=None, **kwargs):
	"""Documents submitted (Monday). Saudi/Kuwait Embassy only."""
	clearance_step_name = clearance_step_name or kwargs.get("name") or kwargs.get("clearance_step")
	if (
		not clearance_step_name
		or not frappe.db.exists("Clearance Step", clearance_step_name)
		or not frappe.db.exists("Placement", frappe.db.get_value("Clearance Step", clearance_step_name, "placement"))
	):
		clearance_step_name = _get_active_step_for_type(["Embassy", "Kuwait Embassy", "Saudi Embassy"])
	if not clearance_step_name:
		frappe.throw("clearance_step_name is required.", frappe.ValidationError)
	step = frappe.get_doc("Clearance Step", clearance_step_name)
	if not _can_act_on_step(step):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if step.status == "Submitted":
		return step.as_dict()
	step.status = "Submitted"
	step.date_started = today()
	step.save(ignore_permissions=True)
	return step.as_dict()


@frappe.whitelist()
def stamp_embassy_step(clearance_step_name=None, reference_no=None, **kwargs):
	"""Documents returned stamped (Thursday) -- the success outcome."""
	clearance_step_name = clearance_step_name or kwargs.get("name") or kwargs.get("clearance_step")
	reference_no = reference_no or kwargs.get("visa_number") or kwargs.get("reference")
	if (
		not clearance_step_name
		or not frappe.db.exists("Clearance Step", clearance_step_name)
		or not frappe.db.exists("Placement", frappe.db.get_value("Clearance Step", clearance_step_name, "placement"))
	):
		clearance_step_name = _get_active_step_for_type(["Embassy", "Kuwait Embassy", "Saudi Embassy"])
	if not clearance_step_name:
		frappe.throw("clearance_step_name is required.", frappe.ValidationError)
	step = frappe.get_doc("Clearance Step", clearance_step_name)
	if not _can_act_on_step(step):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if step.status == "Stamped":
		return step.as_dict()
	step.status = "Stamped"
	step.date_completed = today()
	step.completed_by = frappe.session.user
	if reference_no:
		step.reference_no = reference_no
	step.save(ignore_permissions=True)
	_close_open_todos(clearance_step_name)
	return step.as_dict()


@frappe.whitelist()
def reject_embassy_step(clearance_step_name, rejection_remark):
	"""Documents returned rejected (Thursday) -- requires a written remark
	(Clearance Step.validate() also enforces this as a backstop)."""
	if not rejection_remark:
		frappe.throw("A rejection remark is required.", frappe.ValidationError)
	step = frappe.get_doc("Clearance Step", clearance_step_name)
	if step.step_type not in ("Embassy", "Kuwait Embassy"):
		frappe.throw("Only meaningful for an Embassy clearance step.", frappe.ValidationError)
	if not _can_act_on_step(step):
		frappe.throw("Not permitted.", frappe.PermissionError)
	assert_clearance_step_not_terminal(step)
	step.status = "Rejected"
	step.rejection_remark = rejection_remark
	step.date_completed = today()
	step.completed_by = frappe.session.user
	step.save(ignore_permissions=True)
	_close_open_todos(clearance_step_name)
	return step.as_dict()


@frappe.whitelist()
def reassign_clearance_step(clearance_step_name, new_officer):
	"""Part A.2: "reassignable by a manager if needed" — the escape hatch for the default
	auto-chain."""
	if not ({"Manager", "Admin", "System Manager"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	assert_clearance_step_not_terminal(frappe.get_doc("Clearance Step", clearance_step_name))
	assign_clearance_step(clearance_step_name, new_officer)
	return {"clearance_step": clearance_step_name, "assigned_to": new_officer}


@frappe.whitelist()
def list_my_clearance_steps():
	"""A Clearance Officer / Ticketer's own ToDo-scoped queue."""
	return frappe.get_list(
		"Clearance Step",
		fields=["name", "placement", "step_type", "status", "sequence_order", "is_mandatory"],
		order_by="sequence_order asc",
	)


@frappe.whitelist()
def list_assigned_steps():
	return list_my_clearance_steps()
