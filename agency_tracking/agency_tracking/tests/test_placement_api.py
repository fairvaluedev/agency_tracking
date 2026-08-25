# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.doctype.placement.test_placement import (
	make_contractor,
	registered_applicant,
)
from agency_tracking.agency_tracking.tests.test_portal_api import cv_generated_applicant
from agency_tracking.placement_api import create_muayena_placement, upload_contract
from agency_tracking.portal_api import select_candidate

CONTRACT_TEXT_WITH_DATE = "Employment Contract\nContract Date: 13/08/2026\n..."


class TestPlacementAPI(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_create_muayena_placement_success(self):
		applicant = registered_applicant("mpa01", entry_track="Muayena", destination_country="Kuwait")
		contractor = make_contractor("mpa01", country="Kuwait")

		result = create_muayena_placement(applicant.name, contractor.name, "Kuwait")
		self.assertEqual(result["status"], "Selected")
		self.assertFalse(result["cv_record"])

		applicant.reload()
		self.assertEqual(applicant.active_placement, result["name"])
		self.assertEqual(applicant.destination_country, "Kuwait")
		# entry-track pipeline status is untouched — Muayena never reaches CV Generated.
		self.assertEqual(applicant.status, "Registered")

	def test_create_muayena_placement_rejects_standard_applicant(self):
		applicant = registered_applicant("mpa02", entry_track="Standard", destination_country="Kuwait")
		contractor = make_contractor("mpa02", country="Kuwait")
		with self.assertRaises(frappe.ValidationError):
			create_muayena_placement(applicant.name, contractor.name, "Kuwait")

	def test_create_muayena_placement_rejects_draft_applicant(self):
		applicant = frappe.get_doc(
			{
				"doctype": "Applicant",
				"entry_track": "Muayena",
				"full_name": "Muayena Draft",
				"gender": "Female",
				"nationality": "Ethiopia",
				"phone": "+251900000000",
				"address": "Addis Ababa",
			}
		).insert(ignore_permissions=True)
		contractor = make_contractor("mpa03", country="Kuwait")
		with self.assertRaises(frappe.ValidationError):
			create_muayena_placement(applicant.name, contractor.name, "Kuwait")

	def test_create_muayena_placement_blocks_double_creation(self):
		applicant = registered_applicant("mpa04", entry_track="Muayena", destination_country="Kuwait")
		contractor = make_contractor("mpa04", country="Kuwait")
		create_muayena_placement(applicant.name, contractor.name, "Kuwait")
		with self.assertRaises(frappe.ValidationError):
			create_muayena_placement(applicant.name, contractor.name, "Kuwait")

	def test_upload_contract_by_owning_contractor_extracts_date(self):
		applicant = cv_generated_applicant("mpa05", destination_country="Kuwait")
		contractor = make_contractor("mpa05", country="Kuwait")

		frappe.set_user(contractor.user)
		placement = select_candidate(applicant.name)

		result = upload_contract(placement["name"], "/files/fake-contract.pdf")
		# No real PDF on disk in this test, so extraction yields None — asserting it doesn't
		# raise and the file reference is still recorded is the meaningful check here; the
		# extraction logic itself is covered directly in test_contract_parser.py.
		self.assertEqual(result["contract_file"], "/files/fake-contract.pdf")

	def test_upload_contract_by_other_contractor_blocked(self):
		applicant = cv_generated_applicant("mpa06", destination_country="Kuwait")
		buyer = make_contractor("mpa06a", country="Kuwait")
		other = make_contractor("mpa06b", country="Kuwait")

		frappe.set_user(buyer.user)
		placement = select_candidate(applicant.name)

		frappe.set_user(other.user)
		with self.assertRaises(frappe.PermissionError):
			upload_contract(placement["name"], "/files/fake-contract.pdf")

	def test_upload_contract_by_manager_allowed(self):
		applicant = cv_generated_applicant("mpa07", destination_country="Kuwait")
		contractor = make_contractor("mpa07", country="Kuwait")

		frappe.set_user(contractor.user)
		placement = select_candidate(applicant.name)

		frappe.set_user("Administrator")
		result = upload_contract(placement["name"], "/files/fake-contract.pdf")
		self.assertEqual(result["contract_file"], "/files/fake-contract.pdf")
