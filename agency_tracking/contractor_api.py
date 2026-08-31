# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.
#
# backend-issues #07: Contractor had no whitelisted create/list surface anywhere. A Registrar
# creating a Muayena placement (the documented "contract in hand, no portal" flow) had no
# sanctioned way to pick or register the foreign agency the worker is going to --
# create_muayena_placement's contractor_name is a strict Link to an existing Contractor record.

import frappe

CONTRACTOR_MANAGE_ROLES = {"Manager", "Admin", "Finance Manager", "Registrar"}


@frappe.whitelist()
def create_contractor(contractor_name, country, user_email, user_first_name, communication_manager=None):
	"""Registers a new foreign agency and its portal login in one step -- Contractor.user is a
	required, unique Link (Part G: one Foreign Agency user per Contractor for now), so there's
	no sanctioned way to create a Contractor without also provisioning the User that logs into
	the Wakala portal for it."""
	if not (CONTRACTOR_MANAGE_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)

	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": user_email,
			"first_name": user_first_name,
			"send_welcome_email": 0,
			"roles": [{"role": "Foreign Agency"}],
		}
	).insert(ignore_permissions=True)

	contractor = frappe.get_doc(
		{
			"doctype": "Contractor",
			"contractor_name": contractor_name,
			"country": country,
			"user": user.name,
			"communication_manager": communication_manager,
		}
	).insert(ignore_permissions=True)
	return contractor.as_dict()


@frappe.whitelist()
def list_contractors(filters=None, limit_page_length=100):
	"""Read surface for picking an existing agency (create_muayena_placement's contractor_name,
	Finance's batching/rate lookups). Same role gate as create_contractor -- the doctype's own
	permlevel-0 grants don't cover Registrar/Finance Manager at all, so this uses an explicit
	role check plus frappe.get_all (skips doctype permission checks) rather than frappe.get_list,
	same pattern as finance_api._log_stage_transaction's "permissive write, gated read" shape."""
	if not (CONTRACTOR_MANAGE_ROLES & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	return frappe.get_all(
		"Contractor",
		filters=filters,
		fields=["name", "contractor_name", "country", "user", "communication_manager"],
		limit_page_length=frappe.utils.cint(limit_page_length) or 100,
		order_by="modified desc",
	)
