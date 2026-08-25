# Copyright (c) 2026, Agency and contributors
# See license.txt

import os

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.tests.test_finance_api import make_role_user
from agency_tracking.agency_tracking.tests.test_reconciliation_engine import unsettled_batch, write_csv_file
from agency_tracking.reconciliation_api import manually_match_line, upload_bank_statement


class TestReconciliationAPI(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_upload_requires_finance_role(self):
		officer = make_role_user("ra01", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			upload_bank_statement("/files/nonexistent.csv")

	def test_upload_parses_and_matches_end_to_end(self):
		batch = unsettled_batch("ra02")
		file_url, path = write_csv_file("recon-ra02.csv", [(frappe.utils.today(), "wire", batch.total_amount_birr)])
		try:
			result = upload_bank_statement(file_url)
			self.assertEqual(len(result["lines"]), 1)
			self.assertEqual(result["lines"][0]["match_status"], "Matched")
			self.assertEqual(frappe.db.get_value("Commission Batch Request", batch.name, "status"), "Settled")
		finally:
			os.remove(path)

	def test_manual_match_requires_finance_role(self):
		batch = unsettled_batch("ra03")
		statement = frappe.get_doc(
			{
				"doctype": "Bank Statement",
				"statement_file": "/files/fake.csv",
				"status": "Uploaded",
				"lines": [{"statement_date": frappe.utils.today(), "reference": "unclear", "amount": 999999}],
			}
		).insert(ignore_permissions=True)
		line_name = statement.lines[0].name

		officer = make_role_user("ra03", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			manually_match_line(line_name, batch.name)

	def test_manual_match_settles_batch(self):
		batch = unsettled_batch("ra04")
		statement = frappe.get_doc(
			{
				"doctype": "Bank Statement",
				"statement_file": "/files/fake.csv",
				"status": "Uploaded",
				"lines": [{"statement_date": frappe.utils.today(), "reference": "unclear wire", "amount": 999999}],
			}
		).insert(ignore_permissions=True)
		line_name = statement.lines[0].name

		result = manually_match_line(line_name, batch.name)
		self.assertEqual(result["match_status"], "Manually Matched")
		self.assertEqual(frappe.db.get_value("Commission Batch Request", batch.name, "status"), "Settled")
