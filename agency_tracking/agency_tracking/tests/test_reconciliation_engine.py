# Copyright (c) 2026, Agency and contributors
# See license.txt

import os

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.tests.test_finance_engine import departed_placement
from agency_tracking.finance_engine import create_batch_request, record_fx_rate
from agency_tracking.reconciliation_engine import match_statement_lines, parse_bank_statement_csv


def write_csv_file(filename, rows):
	site_path = frappe.get_site_path("public", "files")
	os.makedirs(site_path, exist_ok=True)
	path = os.path.join(site_path, filename)
	with open(path, "w", newline="", encoding="utf-8") as f:
		f.write("date,reference,amount\n")
		for row in rows:
			f.write(f"{row[0]},{row[1]},{row[2]}\n")
	return f"/files/{filename}", path


def _amount_for_tag(tag):
	# Deterministic per-tag amount (not Python's randomized hash()) so total_amount_birr
	# never accidentally collides across unrelated tests/tags within the same run, which
	# would make "unambiguous single candidate" matching assertions flaky.
	digest = sum((i + 1) * ord(c) for i, c in enumerate(tag))
	return 1000 + (digest % 50000)


def unsettled_batch(tag):
	record_fx_rate("USD", 55.0, frappe.utils.today())
	placement = departed_placement(tag, amount=_amount_for_tag(tag))
	return create_batch_request(placement.contractor, "Saudi Arabia")


class TestReconciliationEngine(FrappeTestCase):
	def test_parse_valid_csv(self):
		file_url, path = write_csv_file(
			"recon-t01.csv", [("2026-08-20", "Wire from Agency X", "13750")]
		)
		try:
			rows = parse_bank_statement_csv(file_url)
			self.assertEqual(len(rows), 1)
			self.assertEqual(rows[0]["amount"], 13750.0)
			self.assertEqual(rows[0]["reference"], "Wire from Agency X")
		finally:
			os.remove(path)

	def test_parse_skips_malformed_rows(self):
		file_url, path = write_csv_file(
			"recon-t02.csv", [("2026-08-20", "Good row", "100"), ("bad-date", "Bad amount row", "not-a-number")]
		)
		try:
			rows = parse_bank_statement_csv(file_url)
			self.assertEqual(len(rows), 1)
		finally:
			os.remove(path)

	def test_unambiguous_amount_match_auto_settles(self):
		batch = unsettled_batch("re01")
		statement = frappe.get_doc(
			{
				"doctype": "Bank Statement",
				"statement_file": "/files/fake.csv",
				"status": "Uploaded",
				"lines": [
					{"statement_date": frappe.utils.today(), "reference": "wire", "amount": batch.total_amount_birr}
				],
			}
		).insert(ignore_permissions=True)

		match_statement_lines(statement)

		statement.reload()
		self.assertEqual(statement.lines[0].match_status, "Matched")
		self.assertEqual(statement.lines[0].matched_batch, batch.name)
		self.assertEqual(frappe.db.get_value("Commission Batch Request", batch.name, "status"), "Settled")

	def test_ambiguous_amount_left_unmatched_without_reference_hint(self):
		batch_a = unsettled_batch("re02a")
		# Force a second batch to have the same total so amount alone can't disambiguate.
		batch_b = unsettled_batch("re02b")
		frappe.db.set_value("Commission Batch Request", batch_b.name, "total_amount_birr", batch_a.total_amount_birr)

		statement = frappe.get_doc(
			{
				"doctype": "Bank Statement",
				"statement_file": "/files/fake.csv",
				"status": "Uploaded",
				"lines": [
					{"statement_date": frappe.utils.today(), "reference": "generic wire", "amount": batch_a.total_amount_birr}
				],
			}
		).insert(ignore_permissions=True)

		match_statement_lines(statement)
		statement.reload()
		self.assertEqual(statement.lines[0].match_status, "Unmatched")

	def test_reference_text_disambiguates_between_equal_amounts(self):
		batch_a = unsettled_batch("re03a")
		batch_b = unsettled_batch("re03b")
		frappe.db.set_value("Commission Batch Request", batch_b.name, "total_amount_birr", batch_a.total_amount_birr)

		statement = frappe.get_doc(
			{
				"doctype": "Bank Statement",
				"statement_file": "/files/fake.csv",
				"status": "Uploaded",
				"lines": [
					{
						"statement_date": frappe.utils.today(),
						"reference": f"Payment ref {batch_a.name}",
						"amount": batch_a.total_amount_birr,
					}
				],
			}
		).insert(ignore_permissions=True)

		match_statement_lines(statement)
		statement.reload()
		self.assertEqual(statement.lines[0].match_status, "Matched")
		self.assertEqual(statement.lines[0].matched_batch, batch_a.name)

	def test_already_settled_batches_excluded_from_candidates(self):
		batch = unsettled_batch("re04")
		from agency_tracking.finance_engine import settle_batch_request

		settle_batch_request(batch.name, "PRE-SETTLED")

		statement = frappe.get_doc(
			{
				"doctype": "Bank Statement",
				"statement_file": "/files/fake.csv",
				"status": "Uploaded",
				"lines": [
					{"statement_date": frappe.utils.today(), "reference": "wire", "amount": batch.total_amount_birr}
				],
			}
		).insert(ignore_permissions=True)

		match_statement_lines(statement)
		statement.reload()
		self.assertEqual(statement.lines[0].match_status, "Unmatched")
