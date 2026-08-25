# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe

# Part G RBAC table, pre-declared in full (see BUILD_LOG.md "Standing decisions") — the
# roles that don't have logic attached yet simply sit unused until their build step.
# "Communication Manager" isn't in the master spec's original Part G table — it's introduced by
# the addendum ("Agencies talk only to Communication Manager"), which explicitly overrides/
# extends Part G. Added here at Step 12 rather than pre-declared with the rest in Step 1,
# since it didn't exist in the spec version Step 1 was built against.
ROLES = [
	"Recruitment/Intake",
	"Clearance Officer",
	"Ticketing/Dispatch",
	"Complaint Manager",
	"Finance Manager",
	"Manager",
	"Admin",
	"Foreign Agency",
	"Communication Manager",
]


# Part A.3 / business-workflow-srs.md Stage 5: the first two configured corridors, proving the
# data-driven engine before anything downstream depends on it. Steps are all mandatory for now
# — the spec doesn't call out an optional step in either corridor yet.
CORRIDORS = {
	"Saudi Arabia": [
		{"step_type": "LMIS Clearance", "sequence_order": 1, "is_mandatory": 1},
		{"step_type": "Taeshir", "sequence_order": 2, "is_mandatory": 1},
		{"step_type": "Injaz", "sequence_order": 3, "is_mandatory": 1},
		{"step_type": "Embassy/Wakala", "sequence_order": 4, "is_mandatory": 1},
	],
	"Kuwait": [
		{"step_type": "LMIS Police Clearance", "sequence_order": 1, "is_mandatory": 1},
		{"step_type": "Telesign", "sequence_order": 2, "is_mandatory": 1},
		{"step_type": "Kuwait Embassy", "sequence_order": 3, "is_mandatory": 1},
		{"step_type": "LMIS Work Permit", "sequence_order": 4, "is_mandatory": 1},
	],
}


def after_install():
	create_roles()
	create_corridors()


def before_tests():
	"""Frappe's standard pre-test-suite hook (wired in hooks.py) — runs once before any test
	module. Without this, whichever test module happens to run first alphabetically implicitly
	determines whether seed data (roles, corridors) exists yet, which is exactly the ordering
	bug this fixes: test_clearance_engine.py < test_corridor_engine.py alphabetically, so
	clearance tests were running before corridor_engine's own tests had a chance to
	self-seed via their create_corridors() calls."""
	create_roles()
	create_corridors()


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


def create_corridors():
	for destination_country, steps in CORRIDORS.items():
		if frappe.db.exists("Corridor Definition", destination_country):
			continue
		frappe.get_doc(
			{
				"doctype": "Corridor Definition",
				"destination_country": destination_country,
				"steps": steps,
			}
		).insert(ignore_permissions=True)
