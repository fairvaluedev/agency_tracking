# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


def draft_applicant(tag):
	return frappe.get_doc(
		{
			"doctype": "Applicant",
			"entry_track": "Standard",
			"full_name": f"Process Event Test {tag}",
			"gender": "Female",
			"nationality": "Ethiopia",
			"phone": "+251900000000",
			"address": "Addis Ababa",
		}
	).insert(ignore_permissions=True)


class TestProcessEvent(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_override_event_requires_remarks(self):
		applicant = draft_applicant("pe01")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Process Event",
					"reference_doctype": "Applicant",
					"reference_name": applicant.name,
					"event_type": "Override",
					"from_status": "Ticketed",
					"to_status": "Departed",
					"actor": "Administrator",
				}
			).insert(ignore_permissions=True)

	def test_transition_event_does_not_require_remarks(self):
		applicant = draft_applicant("pe02")
		doc = frappe.get_doc(
			{
				"doctype": "Process Event",
				"reference_doctype": "Applicant",
				"reference_name": applicant.name,
				"event_type": "Transition",
				"from_status": "Draft",
				"to_status": "Registered",
				"actor": "Administrator",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.event_type, "Transition")

	def test_non_manager_sees_only_own_events(self):
		applicant = draft_applicant("pe03")
		owner = frappe.get_doc(
			{
				"doctype": "User",
				"email": "pe-owner@example.com",
				"first_name": "PE Owner",
				"send_welcome_email": 0,
				"roles": [{"role": "Recruitment/Intake"}],
			}
		).insert(ignore_permissions=True)
		other = frappe.get_doc(
			{
				"doctype": "User",
				"email": "pe-other@example.com",
				"first_name": "PE Other",
				"send_welcome_email": 0,
				"roles": [{"role": "Recruitment/Intake"}],
			}
		).insert(ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "Process Event",
				"reference_doctype": "Applicant",
				"reference_name": applicant.name,
				"event_type": "Transition",
				"from_status": "Draft",
				"to_status": "Registered",
				"actor": owner.name,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Process Event",
				"reference_doctype": "Applicant",
				"reference_name": applicant.name,
				"event_type": "Transition",
				"from_status": "Draft",
				"to_status": "Registered",
				"actor": other.name,
			}
		).insert(ignore_permissions=True)

		frappe.set_user(owner.name)
		visible = frappe.get_list("Process Event", filters={"actor": ["in", [owner.name, other.name]]})
		self.assertEqual(len(visible), 1)

	def test_manager_sees_all_events(self):
		applicant = draft_applicant("pe04")
		manager = frappe.get_doc(
			{
				"doctype": "User",
				"email": "pe-manager@example.com",
				"first_name": "PE Manager",
				"send_welcome_email": 0,
				"roles": [{"role": "Manager"}],
			}
		).insert(ignore_permissions=True)
		someone_else = frappe.get_doc(
			{
				"doctype": "User",
				"email": "pe-else@example.com",
				"first_name": "PE Else",
				"send_welcome_email": 0,
				"roles": [{"role": "Recruitment/Intake"}],
			}
		).insert(ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "Process Event",
				"reference_doctype": "Applicant",
				"reference_name": applicant.name,
				"event_type": "Transition",
				"from_status": "Draft",
				"to_status": "Registered",
				"actor": someone_else.name,
			}
		).insert(ignore_permissions=True)

		frappe.set_user(manager.name)
		visible = frappe.get_list("Process Event", filters={"actor": someone_else.name})
		self.assertEqual(len(visible), 1)
