# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.state_machine import musaned_gate_passed, transition

def standard_floor(tag):
	return {
		"national_id": f"NID-{tag}",
		"labor_id": f"LAB-{tag}",
		"destination_country": "Saudi Arabia",
		"salary_amount": 1500,
		"salary_currency": "SAR",
		"religion": "Muslim",
		"marital_status": "Single",
		"emergency_contact_name": "Abebe Bekele",
		"emergency_contact_phone": "+251911111111",
		"passport_number": f"EP-STD-{tag}",
		"passport_issue_date": "2024-01-01",
		"passport_expiry_date": "2029-01-01",
		"passport_issue_place": "Addis Ababa",
		"date_of_birth": "1998-01-01",
		"education": "High School",
		"target_job": "Housemaid",
		"photograph": "/files/test_photo.jpg",
		"passport_scan": "/files/test_passport.pdf",
		"medical_status": "FIT",
	}


def muayena_floor(tag):
	return {
		"national_id": f"NID-{tag}",
		"passport_number": f"EP-MUA-{tag}",
		"passport_issue_date": "2024-01-01",
		"passport_expiry_date": "2029-01-01",
		"passport_issue_place": "Addis Ababa",
		"date_of_birth": "1998-01-01",
		"photograph": "/files/test_photo.jpg",
		"passport_scan": "/files/test_passport.pdf",
		"medical_status": "FIT",
	}


class TestApplicant(FrappeTestCase):
	def make_draft(self, entry_track="Standard", **overrides):
		data = {
			"doctype": "Applicant",
			"entry_track": entry_track,
			"full_name": "Test Person",
			"gender": "Female",
			"nationality": "Ethiopia",
			"phone": "+251900000000",
			"address": "Addis Ababa",
		}
		data.update(overrides)
		return frappe.get_doc(data).insert(ignore_permissions=True)

	def test_draft_requires_minimum_fields(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Applicant", "entry_track": "Standard"}).insert(
				ignore_permissions=True
			)

	def test_draft_saves_with_minimum_fields(self):
		doc = self.make_draft()
		self.assertEqual(doc.status, "Draft")

	def test_direct_status_write_still_enforces_field_floor(self):
		# transition() is the sanctioned path, but validate() must hold regardless of how
		# status got set — it's the "is the data allowed to exist in this state" check.
		doc = self.make_draft()
		doc.status = "Registered"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_transition_rejects_disallowed_edge(self):
		doc = self.make_draft(**standard_floor("t01"))
		with self.assertRaises(frappe.ValidationError):
			transition(doc, "CV Generated")

	def test_standard_registers_with_full_field_floor(self):
		doc = self.make_draft(**standard_floor("t02"))
		transition(doc, "Registered")
		self.assertEqual(doc.status, "Registered")

	def test_standard_registration_blocked_missing_one_field(self):
		floor = standard_floor("t03")
		floor.pop("labor_id")
		doc = self.make_draft(**floor)
		with self.assertRaises(frappe.ValidationError):
			transition(doc, "Registered")

	def test_registration_blocked_when_medical_not_fit(self):
		floor = standard_floor("t04")
		floor["medical_status"] = "Pending"
		doc = self.make_draft(**floor)
		with self.assertRaises(frappe.ValidationError):
			transition(doc, "Registered")

	def test_muayena_registers_with_lighter_field_floor(self):
		doc = self.make_draft(entry_track="Muayena", **muayena_floor("t05"))
		transition(doc, "Registered")
		self.assertEqual(doc.status, "Registered")

	def test_muayena_does_not_require_standard_only_fields(self):
		# labor_id/salary/religion/etc. are optional/unused for Muayena per Part A.1.
		doc = self.make_draft(entry_track="Muayena", **muayena_floor("t06"))
		self.assertFalse(doc.labor_id)
		transition(doc, "Registered")
		self.assertEqual(doc.status, "Registered")

	def test_passport_number_unique(self):
		floor_a = standard_floor("t07a")
		floor_a["passport_number"] = "EP-DUPLICATE-T07"
		self.make_draft(**floor_a)

		floor_b = standard_floor("t07b")
		floor_b["passport_number"] = "EP-DUPLICATE-T07"
		with self.assertRaises(frappe.DuplicateEntryError):
			self.make_draft(**floor_b)

	def test_multiple_drafts_with_blank_passport_do_not_collide(self):
		self.make_draft()
		self.make_draft()

	def test_musaned_gate_blocks_saudi_standard_without_alteyazechem(self):
		doc = self.make_draft(destination_country="Saudi Arabia", musaned_status="TEYZALECH")
		self.assertFalse(musaned_gate_passed(doc))

	def test_musaned_gate_passes_saudi_standard_with_alteyazechem(self):
		doc = self.make_draft(destination_country="Saudi Arabia", musaned_status="ALTEYAZECHEM")
		self.assertTrue(musaned_gate_passed(doc))

	def test_musaned_gate_not_applicable_to_kuwait(self):
		doc = self.make_draft(destination_country="Kuwait", musaned_status="TEYZALECH")
		self.assertTrue(musaned_gate_passed(doc))

	def test_musaned_gate_not_applicable_to_muayena(self):
		doc = self.make_draft(entry_track="Muayena", destination_country="Saudi Arabia", musaned_status="TEYZALECH")
		self.assertTrue(musaned_gate_passed(doc))
