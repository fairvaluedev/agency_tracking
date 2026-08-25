# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe

# Part G RBAC table, pre-declared in full (see BUILD_LOG.md "Standing decisions") — the
# roles that don't have logic attached yet simply sit unused until their build step.
ROLES = [
	"Recruitment/Intake",
	"Clearance Officer",
	"Ticketing/Dispatch",
	"Complaint Manager",
	"Finance Manager",
	"Manager",
	"Admin",
	"Foreign Agency",
]


def after_install():
	create_roles()


def create_roles():
	for role_name in ROLES:
		if frappe.db.exists("Role", role_name):
			continue
		# Foreign Agency is portal-only (Part G) — never gets Desk access.
		desk_access = 0 if role_name == "Foreign Agency" else 1
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": desk_access,
			}
		).insert(ignore_permissions=True)
