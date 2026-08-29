import unittest

from agency_tracking.passport_parser import (
	compute_icao_checksum,
	verify_and_correct_checksum,
	parse_mrz_td3,
	parse_mrz_td1,
	extract_mrz_from_raw_text,
	map_mrz_fields,
)


class TestPassportMRZEngine(unittest.TestCase):
	def test_icao_checksum_computation(self):
		# Standard ICAO 9303 test vector: "L8988901C" -> check digit is 4
		# L (21)*7 + 8*3 + 9*1 + 8*7 + 8*3 + 9*1 + 0*7 + 1*3 + C (12)*1 = 284 % 10 = 4
		chk = compute_icao_checksum("L8988901C")
		self.assertEqual(chk, 4)

	def test_td3_mrz_parsing_and_checksum_validation(self):
		line1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
		line2 = "L8988901C4UTO6908061F9406236ZE184226B<<<<<10"

		parsed = parse_mrz_td3(line1, line2)
		self.assertEqual(parsed["passport_number"], "L8988901C")
		self.assertEqual(parsed["first_name"], "Anna")
		self.assertEqual(parsed["middle_name"], "Maria")
		self.assertEqual(parsed["last_name"], "Eriksson")
		self.assertEqual(parsed["gender"], "Female")
		self.assertEqual(parsed["date_of_birth"], "1969-08-06")
		self.assertEqual(parsed["passport_expiry"], "1994-06-23")
		self.assertTrue(parsed["checksum_validation"]["passport_number"]["valid"])
		self.assertTrue(parsed["checksum_validation"]["date_of_birth"]["valid"])
		self.assertTrue(parsed["checksum_validation"]["expiry_date"]["valid"])

	def test_ethiopian_passport_mrz_parsing(self):
		line1 = "PQETHWACHAMO<<ASNEKECH<TEDESSE<<<<<<<<<<<<<<<<"
		line2 = "EQ25760963ETH0012027F30051210<<<<<<<<<<<<<<04"

		parsed = parse_mrz_td3(line1, line2)
		self.assertEqual(parsed["passport_number"], "EQ2576096")
		self.assertEqual(parsed["first_name"], "Asnekech")
		self.assertEqual(parsed["middle_name"], "Tedesse")
		self.assertEqual(parsed["last_name"], "Wachamo")
		self.assertEqual(parsed["full_name"], "Asnekech Tedesse Wachamo")
		self.assertEqual(parsed["nationality"], "Ethiopia")
		self.assertEqual(parsed["gender"], "Female")
		self.assertEqual(parsed["date_of_birth"], "2000-12-02")
		self.assertEqual(parsed["passport_expiry"], "2030-05-12")
		self.assertEqual(parsed["passport_issue_date"], "2025-05-12")
		self.assertTrue(parsed["checksum_validation"]["passport_number"]["valid"])
		self.assertTrue(parsed["checksum_validation"]["date_of_birth"]["valid"])
		self.assertTrue(parsed["checksum_validation"]["expiry_date"]["valid"])

	def test_checksum_self_correction(self):
		# Test case where OCR misidentified '0' as 'O'
		# 9*7 + 8*3 + 0*1 + 5*7 + 1*3 + 4*1 = 63 + 24 + 0 + 35 + 3 + 4 = 129 % 10 = 9
		raw_dob_with_ocr_error = "98O514"
		val, corr, chk = verify_and_correct_checksum(raw_dob_with_ocr_error, "9", is_numeric=True)
		self.assertTrue(val)
		self.assertEqual(corr, "980514")
		self.assertEqual(chk, "9")

	def test_map_mrz_fields_backward_compatibility(self):
		mrz_dict = {
			"number": "EQ1234567",
			"expiration_date": "300512",
			"date_of_birth": "001202",
			"sex": "F",
			"names": "Asnekech Tedesse",
			"surname": "Wachamo",
			"nationality": "Ethiopia",
		}
		mapped = map_mrz_fields(mrz_dict)
		self.assertEqual(mapped["passport_number"], "EQ1234567")
		self.assertEqual(mapped["gender"], "Female")
		self.assertEqual(mapped["first_name"], "Asnekech Tedesse")
		self.assertEqual(mapped["last_name"], "Wachamo")
