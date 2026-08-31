# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.contractor_api import create_contractor, list_contractors


def make_role_user(tag, role):
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": f"ca-{tag}@example.com",
			"first_name": f"CA {tag}",
			"send_welcome_email": 0,
			"roles": [{"role": role}],
		}
	).insert(ignore_permissions=True)


class TestContractorAPI(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_registrar_can_create_contractor(self):
		# backend-issues #07: a Registrar creating a Muayena placement previously had no
		# sanctioned way to register the foreign agency contractor_name links to.
		registrar = make_role_user("ctr01", "Registrar")
		frappe.set_user(registrar.name)

		result = create_contractor("Test Agency ctr01", "Kuwait", "ctr01-agency@example.com", "Agency Ctr01")
		self.assertEqual(result["contractor_name"], "Test Agency ctr01")
		self.assertTrue(frappe.db.exists("User", result["user"]))
		self.assertIn("Foreign Agency", frappe.get_roles(result["user"]))

	def test_create_contractor_denied_for_unrelated_role(self):
		officer = make_role_user("ctr02", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			create_contractor("Test Agency ctr02", "Kuwait", "ctr02-agency@example.com", "Agency Ctr02")

	def test_registrar_can_list_contractors(self):
		create_contractor("Test Agency ctr03", "Saudi Arabia", "ctr03-agency@example.com", "Agency Ctr03")

		registrar = make_role_user("ctr03b", "Registrar")
		frappe.set_user(registrar.name)
		result = list_contractors(filters={"contractor_name": "Test Agency ctr03"})
		self.assertEqual(len(result), 1)

	def test_list_contractors_denied_for_unrelated_role(self):
		officer = make_role_user("ctr04", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			list_contractors()
