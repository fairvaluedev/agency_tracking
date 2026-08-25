# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.state_machine import transition


def registered_applicant(tag, entry_track="Standard", destination_country="Kuwait", musaned_status=None):
	if musaned_status is None:
		musaned_status = "ALTEYAZECHEM" if destination_country == "Saudi Arabia" else "Not Applicable"
	if entry_track == "Standard":
		data = {
			"doctype": "Applicant",
			"entry_track": "Standard",
			"full_name": f"Placement Test {tag}",
			"gender": "Female",
			"nationality": "Ethiopia",
			"phone": "+251900000000",
			"address": "Addis Ababa",
			"national_id": f"NID-PLM-{tag}",
			"labor_id": f"LAB-PLM-{tag}",
			"destination_country": destination_country,
			"salary_amount": 1500,
			"salary_currency": "SAR",
			"religion": "Muslim",
			"marital_status": "Single",
			"emergency_contact_name": "Abebe",
			"emergency_contact_phone": "+251911111111",
			"passport_number": f"EP-PLM-{tag}",
			"passport_issue_date": "2024-01-01",
			"passport_expiry_date": "2029-01-01",
			"passport_issue_place": "Addis Ababa",
			"date_of_birth": "1998-01-01",
			"education": "High School",
			"target_job": "Housemaid",
			"musaned_status": musaned_status,
			"photograph": "/files/test_photo.jpg",
			"passport_scan": "/files/test_passport.pdf",
			"medical_status": "FIT",
		}
	else:
		data = {
			"doctype": "Applicant",
			"entry_track": "Muayena",
			"full_name": f"Placement Test Muayena {tag}",
			"gender": "Female",
			"nationality": "Ethiopia",
			"phone": "+251900000000",
			"address": "Addis Ababa",
			"national_id": f"NID-PLMM-{tag}",
			"passport_number": f"EP-PLMM-{tag}",
			"passport_issue_date": "2024-01-01",
			"passport_expiry_date": "2029-01-01",
			"passport_issue_place": "Addis Ababa",
			"date_of_birth": "1998-01-01",
			"photograph": "/files/test_photo.jpg",
			"passport_scan": "/files/test_passport.pdf",
			"medical_status": "FIT",
			"destination_country": destination_country,
		}
	doc = frappe.get_doc(data).insert(ignore_permissions=True)
	transition(doc, "Registered")
	return doc


def make_contractor(tag, country="Kuwait"):
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": f"agency-{tag}@example.com",
			"first_name": f"Agency{tag}",
			"send_welcome_email": 0,
			"roles": [{"role": "Foreign Agency"}],
		}
	).insert(ignore_permissions=True)
	return frappe.get_doc(
		{
			"doctype": "Contractor",
			"contractor_name": f"Test Agency {tag}",
			"country": country,
			"user": user.name,
		}
	).insert(ignore_permissions=True)


class TestPlacement(FrappeTestCase):
	def test_muayena_placement_creation_blocked(self):
		applicant = registered_applicant("t01", entry_track="Muayena")
		contractor = make_contractor("t01")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Placement",
					"applicant": applicant.name,
					"contractor": contractor.name,
					"destination_country": "Kuwait",
					"status": "Selected",
				}
			).insert(ignore_permissions=True)

	def test_destination_country_mismatch_blocked(self):
		applicant = registered_applicant("t02", destination_country="Kuwait")
		contractor = make_contractor("t02", country="Saudi Arabia")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Placement",
					"applicant": applicant.name,
					"contractor": contractor.name,
					"destination_country": "Saudi Arabia",
					"status": "Selected",
				}
			).insert(ignore_permissions=True)

	def test_duplicate_active_placement_blocked(self):
		applicant = registered_applicant("t03", destination_country="Kuwait")
		contractor = make_contractor("t03")
		placement = frappe.get_doc(
			{
				"doctype": "Placement",
				"applicant": applicant.name,
				"contractor": contractor.name,
				"destination_country": "Kuwait",
				"status": "Selected",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Applicant", applicant.name, "active_placement", placement.name)
		applicant.reload()

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Placement",
					"applicant": applicant.name,
					"contractor": contractor.name,
					"destination_country": "Kuwait",
					"status": "Selected",
				}
			).insert(ignore_permissions=True)

	def test_valid_placement_creates(self):
		applicant = registered_applicant("t04", destination_country="Kuwait")
		contractor = make_contractor("t04")
		placement = frappe.get_doc(
			{
				"doctype": "Placement",
				"applicant": applicant.name,
				"contractor": contractor.name,
				"destination_country": "Kuwait",
				"status": "Selected",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(placement.status, "Selected")
