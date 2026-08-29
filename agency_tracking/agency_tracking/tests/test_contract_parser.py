# Copyright (c) 2026, Agency and contributors
# See license.txt

from frappe.tests.utils import FrappeTestCase

from agency_tracking.contract_parser import (
	extract_contract_signed_date,
	normalize_date_string,
	normalize_text,
	ContractTextStructurizer,
	extract_saudi_fields,
	extract_kuwait_fields,
	extract_visa_fields,
	parse_structured_contract_text,
)


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

	def test_arabic_presentation_form_normalization(self):
		# Test isolated/presentation Arabic chars get normalized to standard Arabic
		presentation_text = "\ufe8d\ufe91\ufee0\ufeae\ufecb"  # Presentation forms for Arabic letters
		cleaned = normalize_text(presentation_text)
		self.assertIsInstance(cleaned, str)
		self.assertTrue(len(cleaned) > 0)

	def test_saudi_musaned_contract_parsing(self):
		raw_text = """
CONTRACT # 2005450415
VISA NUMBER # 1908334046
corresponding to (13/08/2026)

A. Employer:
Name: ABDULLAH AMER MUGHABBIRI ALBARIQI
National ID Number: 1098765432
Street: King Fahd Road, Al Malaz District
City: Riyadh

Saudi Recruiting Agency:
Name: Al Qurashi Recruitment Office Co.
License no: 7788
Telephone: +966501234567

6. Wage:
fixed monthly wage of 1000 (Saudi Riyals)
"""
		parsed = parse_structured_contract_text(raw_text)
		self.assertEqual(parsed["contract_number"], "2005450415")
		self.assertEqual(parsed["visa_number"], "1908334046")
		self.assertEqual(parsed["contract_signed_date"], "2026-08-13")
		self.assertIn("ABDULLAH", parsed["employer_name"])
		self.assertEqual(parsed["employer_national_id"], "1098765432")
		self.assertIn("Al Qurashi", parsed["saudi_agency_name"])
		self.assertEqual(parsed["saudi_agency_license"], "7788")
		self.assertEqual(parsed["contract_salary_amount"], 1000.0)
		self.assertEqual(parsed["contract_salary_currency"], "SAR")

	def test_kuwait_contract_parsing(self):
		raw_text = """
Contract of Employment
Date: 2026-08-15
Employer Name: ABDULLAH AL-SABAH
Employment site: Kaifan
Duration of the contract: 2 years starting from arrival
Monthly salary: 120 KWD
"""
		kuwait = extract_kuwait_fields(raw_text)
		self.assertIn("ABDULLAH", kuwait["employer_name"])
		self.assertIn("Kaifan", kuwait["employment_site"])
		self.assertEqual(kuwait["contract_salary_amount"], 120.0)
		self.assertEqual(kuwait["contract_salary_currency"], "KWD")

	def test_kuwait_visa_parsing(self):
		visa_text = """
State of Kuwait - Ministry of Interior
Visa Number: 987654321
Visa Type: Domestic Worker - Art 20
Issue Date: 15/08/2026
Expiry Date: 15/11/2026
Reference: 55443322
Fahad Al-Otaibi - 280010112345 - Kuwait
Al-Hilal Agency - 1234
"""
		visa = extract_visa_fields(visa_text)
		self.assertEqual(visa["visa_number"], "987654321")
		self.assertEqual(visa["visa_issue_date"], "2026-08-15")
		self.assertEqual(visa["visa_expiry_date"], "2026-11-15")
		self.assertEqual(visa["visa_reference_number"], "55443322")

	def test_injaz_paper_parsing(self):
		from agency_tracking.contract_parser import extract_injaz_fields
		injaz_text = """
1908078445
E822520861
Sponsor : YOUSEF DABBOUR
EMBASSY OF SAUDI ARABIA
CONSULAR SECTION
ANWAR SULTAN FOREIGN EMPLOYMENT AGENT
Full Name :
JEMILA SEID HUSSEN
Date of Birth :
17/06/1988
Place of Birth :
SILTE
Current Nationality : Ethiopia
Sex :
Female
Religion :
Islam
Pasport No: EP8943504
Date of Issue : 11/07/2024
Date of Expiry :
10/07/2029
"""
		injaz = extract_injaz_fields(injaz_text)
		self.assertEqual(injaz["injaz_number"], "1908078445")
		self.assertEqual(injaz["sponsor_name"], "YOUSEF DABBOUR")
		self.assertEqual(injaz["full_name"], "JEMILA SEID HUSSEN")
		self.assertEqual(injaz["date_of_birth"], "1988-06-17")
		self.assertEqual(injaz["place_of_birth"], "SILTE")
		self.assertEqual(injaz["gender"], "Female")
		self.assertEqual(injaz["religion"], "Islam")
		self.assertEqual(injaz["passport_number"], "EP8943504")
		self.assertEqual(injaz["passport_issue_date"], "2024-07-11")
		self.assertEqual(injaz["passport_expiry_date"], "2029-07-10")


