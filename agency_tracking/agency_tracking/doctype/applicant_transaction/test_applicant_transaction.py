# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestApplicantTransaction(FrappeTestCase):
	def test_amount_birr_always_recomputed_from_original_and_rate(self):
		doc = frappe.get_doc(
			{
				"doctype": "Applicant Transaction",
				"transaction_type": "Income",
				"amount_original": 100,
				"currency_original": "USD",
				"fx_rate": 55.5,
				"fx_rate_date": frappe.utils.today(),
				"amount_birr": 1,  # deliberately wrong — validate() must overwrite this
				"logged_by": "Administrator",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.amount_birr, 5550.0)
