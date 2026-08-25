# Copyright (c) 2026, Agency and contributors
# See license.txt

from frappe.tests.utils import FrappeTestCase

from agency_tracking.contract_parser import extract_contract_signed_date, normalize_date_string


class TestContractParser(FrappeTestCase):
	def test_extract_english_labelled_date(self):
		text = "Employment Contract\nContract Date: 13/08/2026\nParty A: ..."
		self.assertEqual(extract_contract_signed_date(text), "2026-08-13")

	def test_extract_iso_date(self):
		text = "Agreement Date - 2026-08-13\n..."
		self.assertEqual(extract_contract_signed_date(text), "2026-08-13")

	def test_extract_arabic_labelled_date(self):
		text = "عقد استقدام\nتاريخ العقد: 13/08/2026\nالطرف الأول: ..."
		self.assertEqual(extract_contract_signed_date(text), "2026-08-13")

	def test_no_match_returns_none(self):
		self.assertIsNone(extract_contract_signed_date("No dates in here at all."))

	def test_empty_text_returns_none(self):
		self.assertIsNone(extract_contract_signed_date(""))
		self.assertIsNone(extract_contract_signed_date(None))

	def test_normalize_date_string_day_first(self):
		self.assertEqual(normalize_date_string("13/08/2026"), "2026-08-13")

	def test_normalize_date_string_year_first(self):
		self.assertEqual(normalize_date_string("2026-08-13"), "2026-08-13")

	def test_normalize_date_string_invalid(self):
		self.assertIsNone(normalize_date_string("not a date"))
