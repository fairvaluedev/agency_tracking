# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.cv_api import generate_cv
from agency_tracking.state_machine import transition


def registered_standard_applicant(tag, destination_country="Kuwait", musaned_status="Not Applicable"):
	doc = frappe.get_doc(
		{
			"doctype": "Applicant",
			"entry_track": "Standard",
			"full_name": f"CV Test {tag}",
			"gender": "Female",
			"nationality": "Ethiopia",
			"phone": "+251900000000",
			"address": "Addis Ababa",
			"national_id": f"NID-CV-{tag}",
			"labor_id": f"LAB-CV-{tag}",
			"destination_country": destination_country,
			"salary_amount": 1500,
			"salary_currency": "SAR",
			"religion": "Muslim",
			"marital_status": "Single",
			"emergency_contact_name": "Abebe",
			"emergency_contact_phone": "+251911111111",
			"passport_number": f"EP-CV-{tag}",
			"passport_issue_date": "2024-01-01",
			"passport_expiry_date": "2029-01-01",
			"passport_issue_place": "Addis Ababa",
			"date_of_birth": "1998-01-01",
			"education": "High School",
			"target_job": "Housemaid",
			"photograph": "/files/test_photo.jpg",
			"passport_scan": "/files/test_passport.pdf",
			"medical_status": "FIT",
			"musaned_status": musaned_status,
		}
	).insert(ignore_permissions=True)
	transition(doc, "Registered")
	return doc


def registered_muayena_applicant(tag):
	doc = frappe.get_doc(
		{
			"doctype": "Applicant",
			"entry_track": "Muayena",
			"full_name": f"CV Test Muayena {tag}",
			"gender": "Female",
			"nationality": "Ethiopia",
			"phone": "+251900000000",
			"address": "Addis Ababa",
			"national_id": f"NID-CVM-{tag}",
			"destination_country": "Saudi Arabia",
			"passport_number": f"EP-CVM-{tag}",
			"passport_issue_date": "2024-01-01",
			"passport_expiry_date": "2029-01-01",
			"passport_issue_place": "Addis Ababa",
			"date_of_birth": "1998-01-01",
			"photograph": "/files/test_photo.jpg",
			"passport_scan": "/files/test_passport.pdf",
			"medical_status": "FIT",
		}
	).insert(ignore_permissions=True)
	transition(doc, "Registered")
	return doc


class TestCVRecord(FrappeTestCase):
	def test_kuwait_standard_generates_cv_without_musaned(self):
		applicant = registered_standard_applicant("t01", destination_country="Kuwait")
		result = generate_cv(applicant.name)
		self.assertEqual(result["applicant_status"], "CV Generated")
		self.assertEqual(frappe.db.get_value("CV Record", result["cv_record"], "docstatus"), 1)

	def test_saudi_standard_generates_cv_regardless_of_musaned_status(self):
		# 2026-08-29: the Musaned gate was removed -- CV generation for Saudi-bound Standard
		# candidates no longer depends on musaned_status at all. The field itself is still
		# tracked as data, just no longer a blocking gate.
		applicant = registered_standard_applicant(
			"t02", destination_country="Saudi Arabia", musaned_status="TEYZALECH"
		)
		result = generate_cv(applicant.name)
		self.assertEqual(result["applicant_status"], "CV Generated")

	def test_saudi_standard_generates_cv_with_alteyazechem(self):
		applicant = registered_standard_applicant(
			"t04", destination_country="Saudi Arabia", musaned_status="ALTEYAZECHEM"
		)
		result = generate_cv(applicant.name)
		self.assertEqual(result["applicant_status"], "CV Generated")

	def test_muayena_cannot_generate_cv(self):
		applicant = registered_muayena_applicant("t05")
		with self.assertRaises(frappe.ValidationError):
			generate_cv(applicant.name)

	def test_draft_applicant_cannot_generate_cv(self):
		applicant = frappe.get_doc(
			{
				"doctype": "Applicant",
				"entry_track": "Standard",
				"full_name": "CV Test Draft",
				"gender": "Female",
				"nationality": "Ethiopia",
				"phone": "+251900000000",
				"address": "Addis Ababa",
			}
		).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			generate_cv(applicant.name)
