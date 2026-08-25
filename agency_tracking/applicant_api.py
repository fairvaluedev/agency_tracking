# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: no raw /api/resource/* exposure. Every client-facing operation is a whitelisted
# function in a module-scoped file. This is the first of those files (applicant_api.py named
# explicitly in Part F's surface list); more (placement_api.py, finance_api.py, chat_api.py,
# report_api.py) are added as their build steps land.

import frappe

from agency_tracking.state_machine import transition


@frappe.whitelist()
def create_applicant(**data):
	"""Open a new Applicant file at Draft. Recruitment/Intake, Manager, Admin only
	(doctype-level create permission, Part G)."""
	if not frappe.has_permission("Applicant", "create"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	data = dict(data)
	data["doctype"] = "Applicant"
	data["status"] = "Draft"
	doc = frappe.get_doc(data).insert()
	return doc.as_dict()


@frappe.whitelist()
def update_applicant(applicant_name, **data):
	"""Edit an Applicant still at Draft or Registered. Does not change status — use
	register_applicant for that transition."""
	doc = frappe.get_doc("Applicant", applicant_name)
	if not doc.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	data = dict(data)
	data.pop("status", None)
	data.pop("doctype", None)
	data.pop("name", None)
	doc.update(data)
	doc.save()
	return doc.as_dict()


@frappe.whitelist()
def register_applicant(applicant_name):
	"""Move an Applicant from Draft to Registered via the sanctioned transition() path
	(Part A.2 Stage 2). Field-floor and medical-FIT checks run inside Applicant.validate(),
	triggered by transition()'s doc.save()."""
	doc = frappe.get_doc("Applicant", applicant_name)
	if not doc.has_permission("write"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	transition(doc, "Registered")
	return doc.as_dict()


@frappe.whitelist()
def get_applicant(applicant_name):
	doc = frappe.get_doc("Applicant", applicant_name)
	if not doc.has_permission("read"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	return doc.as_dict()
