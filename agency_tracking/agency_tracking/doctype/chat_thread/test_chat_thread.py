# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.doctype.placement.test_placement import make_contractor


class TestChatThread(FrappeTestCase):
	def test_agency_thread_requires_contractor(self):
		manager = frappe.get_doc(
			{
				"doctype": "User",
				"email": "ct01-manager@example.com",
				"first_name": "CT Manager",
				"send_welcome_email": 0,
				"roles": [{"role": "Communication Manager"}],
			}
		).insert(ignore_permissions=True)
		contractor = make_contractor("ct01", country="Kuwait")

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Chat Thread",
					"thread_type": "Agency",
					"participants": [{"user": contractor.user}, {"user": manager.name}],
				}
			).insert(ignore_permissions=True)

	def test_agency_thread_requires_exactly_two_participants(self):
		manager = frappe.get_doc(
			{
				"doctype": "User",
				"email": "ct02-manager@example.com",
				"first_name": "CT Manager 2",
				"send_welcome_email": 0,
				"roles": [{"role": "Communication Manager"}],
			}
		).insert(ignore_permissions=True)
		contractor = make_contractor("ct02", country="Kuwait")

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Chat Thread",
					"thread_type": "Agency",
					"contractor": contractor.name,
					"participants": [{"user": contractor.user}],
				}
			).insert(ignore_permissions=True)

	def test_valid_agency_thread_succeeds(self):
		manager = frappe.get_doc(
			{
				"doctype": "User",
				"email": "ct03-manager@example.com",
				"first_name": "CT Manager 3",
				"send_welcome_email": 0,
				"roles": [{"role": "Communication Manager"}],
			}
		).insert(ignore_permissions=True)
		contractor = make_contractor("ct03", country="Kuwait")

		thread = frappe.get_doc(
			{
				"doctype": "Chat Thread",
				"thread_type": "Agency",
				"contractor": contractor.name,
				"participants": [{"user": contractor.user}, {"user": manager.name}],
			}
		).insert(ignore_permissions=True)
		self.assertEqual(thread.thread_type, "Agency")

	def test_foreign_agency_user_blocked_from_internal_thread(self):
		contractor = make_contractor("ct04", country="Kuwait")
		staff = frappe.get_doc(
			{
				"doctype": "User",
				"email": "ct04-staff@example.com",
				"first_name": "CT Staff",
				"send_welcome_email": 0,
				"roles": [{"role": "Recruitment/Intake"}],
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Chat Thread",
					"thread_type": "Internal",
					"participants": [{"user": contractor.user}, {"user": staff.name}],
				}
			).insert(ignore_permissions=True)
