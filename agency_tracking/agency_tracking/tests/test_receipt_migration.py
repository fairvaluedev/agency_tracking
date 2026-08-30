# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.finance_engine import record_fx_rate


def make_local_file(tag):
	return frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"receipt-{tag}.txt",
			"is_private": 0,
			"content": b"dummy receipt bytes",
		}
	).insert(ignore_permissions=True)


class TestReceiptMigration(FrappeTestCase):
	def test_receipt_upload_never_blocks_save_when_r2_not_configured(self):
		# Storage Settings has no credentials in this test env -- migrate_attach_to_r2 must
		# swallow the resulting error and leave the local file in place, never abort the save.
		record_fx_rate("USD", 55.0, frappe.utils.today())
		file_doc = make_local_file("rm01")

		txn = frappe.get_doc(
			{
				"doctype": "Applicant Transaction",
				"transaction_type": "Expense",
				"amount_original": 10,
				"currency_original": "USD",
				"fx_rate": 55.0,
				"fx_rate_date": frappe.utils.today(),
				"receipt_image": file_doc.file_url,
				"logged_by": "Administrator",
			}
		).insert(ignore_permissions=True)

		self.assertTrue(frappe.db.exists("Applicant Transaction", txn.name))
		# Still the local file URL -- migration failed gracefully (not configured), didn't crash.
		self.assertTrue(txn.receipt_image.startswith("/files/") or txn.receipt_image.startswith("/private/files/"))

	def test_already_migrated_url_is_left_alone(self):
		from agency_tracking.storage_engine import migrate_attach_to_r2

		txn = frappe.get_doc(
			{
				"doctype": "Applicant Transaction",
				"transaction_type": "Expense",
				"amount_original": 10,
				"currency_original": "USD",
				"fx_rate": 1,
				"fx_rate_date": frappe.utils.today(),
				"receipt_image": "https://example-bucket.r2.dev/agency/APP-1/finance-receipts/x.png",
				"logged_by": "Administrator",
			}
		)
		migrate_attach_to_r2(txn, "receipt_image", "finance-receipts", applicant_name="APP-1")
		self.assertEqual(
			txn.receipt_image, "https://example-bucket.r2.dev/agency/APP-1/finance-receipts/x.png"
		)
