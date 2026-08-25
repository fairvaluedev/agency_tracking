# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.tests.test_state_machine import selected_placement
from agency_tracking.clearance_engine import assign_clearance_step
from agency_tracking.state_machine import transition


class TestClearanceStep(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_officer_sees_only_assigned_row_not_others(self):
		placement = selected_placement("cs01")
		transition(placement, "Processing")
		steps = frappe.get_all(
			"Clearance Step", filters={"placement": placement.name}, order_by="sequence_order asc"
		)
		self.assertGreaterEqual(len(steps), 2)

		officer = frappe.get_doc(
			{
				"doctype": "User",
				"email": "cs-officer@example.com",
				"first_name": "CS Officer",
				"send_welcome_email": 0,
				"roles": [{"role": "Clearance Officer"}],
			}
		).insert(ignore_permissions=True)
		assign_clearance_step(steps[0].name, officer.name)

		frappe.set_user(officer.name)
		visible = frappe.get_list("Clearance Step", filters={"placement": placement.name})
		self.assertEqual(len(visible), 1)
		self.assertEqual(visible[0].name, steps[0].name)

	def test_manager_sees_all_rows(self):
		placement = selected_placement("cs02")
		transition(placement, "Processing")

		manager = frappe.get_doc(
			{
				"doctype": "User",
				"email": "cs-manager@example.com",
				"first_name": "CS Manager",
				"send_welcome_email": 0,
				"roles": [{"role": "Manager"}],
			}
		).insert(ignore_permissions=True)

		frappe.set_user(manager.name)
		visible = frappe.get_list("Clearance Step", filters={"placement": placement.name})
		all_steps = frappe.get_all("Clearance Step", filters={"placement": placement.name})
		self.assertEqual(len(visible), len(all_steps))

	def test_role_without_any_grant_is_denied_outright(self):
		# Recruitment/Intake has no read/write permission row on Clearance Step at all (Part G:
		# their scope is Applicant through Stage 3) — Frappe denies at the base doctype-
		# permission check, before permission_query_conditions ever runs, so this is a
		# PermissionError rather than an empty result set.
		placement = selected_placement("cs03")
		transition(placement, "Processing")

		outsider = frappe.get_doc(
			{
				"doctype": "User",
				"email": "cs-outsider@example.com",
				"first_name": "CS Outsider",
				"send_welcome_email": 0,
				"roles": [{"role": "Recruitment/Intake"}],
			}
		).insert(ignore_permissions=True)

		frappe.set_user(outsider.name)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list("Clearance Step", filters={"placement": placement.name})
