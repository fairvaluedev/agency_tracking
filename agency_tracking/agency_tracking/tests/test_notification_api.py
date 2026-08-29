# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.tests.test_watchdogs import contractor_user_for, placement_with_lmis_officer
from agency_tracking.notification_api import subscribe_to_push, trigger_wakala_reminder


class TestNotificationAPI(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_subscribe_to_push_uses_session_user_not_arbitrary_target(self):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "napi-self@example.com",
				"first_name": "Self",
				"send_welcome_email": 0,
				"roles": [{"role": "Clearance Officer"}],
			}
		).insert(ignore_permissions=True)
		frappe.set_user(user.name)
		subscribe_to_push("https://push.example.com/self", "k", "a")
		self.assertTrue(frappe.db.exists("Push Subscription", {"user": user.name}))

	def test_trigger_wakala_reminder_rejects_wrong_step_type(self):
		placement, officer = placement_with_lmis_officer("na01")
		lmis_step = frappe.db.get_value(
			"Clearance Step", {"placement": placement.name, "step_type": "LMIS Clearance"}, "name"
		)
		with self.assertRaises(frappe.ValidationError):
			trigger_wakala_reminder(lmis_step)

	def test_trigger_wakala_reminder_manual_trigger_succeeds(self):
		# Saudi corridor already auto-creates an Embassy step on entering Processing (Step 7)
		# — use that one rather than inserting a redundant second step.
		placement, officer = placement_with_lmis_officer("na02")
		recipient = contractor_user_for(placement)
		wakala_step_name = frappe.db.get_value(
			"Clearance Step", {"placement": placement.name, "step_type": "Embassy"}, "name"
		)

		result = trigger_wakala_reminder(wakala_step_name)
		self.assertEqual(result["status"], "reminder sent")
		self.assertTrue(
			frappe.db.exists("Comms Log", {"recipient": recipient, "template": "wakala_payment_reminder"})
		)

	def test_trigger_wakala_reminder_requires_read_permission(self):
		placement, officer = placement_with_lmis_officer("na03")
		wakala_step_name = frappe.db.get_value(
			"Clearance Step", {"placement": placement.name, "step_type": "Embassy"}, "name"
		)

		outsider = frappe.get_doc(
			{
				"doctype": "User",
				"email": "na03-outsider@example.com",
				"first_name": "Outsider",
				"send_welcome_email": 0,
				"roles": [{"role": "Registrar"}],
			}
		).insert(ignore_permissions=True)
		frappe.set_user(outsider.name)
		with self.assertRaises(frappe.PermissionError):
			trigger_wakala_reminder(wakala_step_name)
