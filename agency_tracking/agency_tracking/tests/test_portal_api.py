# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.doctype.placement.test_placement import (
	make_contractor,
	registered_applicant,
)
from agency_tracking.cv_api import generate_cv
from agency_tracking.portal_api import list_portal_candidates, select_candidate


def cv_generated_applicant(tag, destination_country="Kuwait"):
	applicant = registered_applicant(tag, destination_country=destination_country)
	generate_cv(applicant.name)
	applicant.reload()
	return applicant


class TestPortalAPI(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_catalog_filters_by_contractor_country(self):
		# Asserts the specific candidate is present/absent rather than an exact total count —
		# list_portal_candidates() is correctly system-wide for a given country (any agency in
		# Kuwait sees every unclaimed Kuwait candidate, not just ones this test created), so an
		# exact-count assertion is fragile against any other Kuwait CV-Generated candidate
		# existing anywhere in the DB — including from manual site data outside the test
		# framework entirely, which is exactly what broke this the first time.
		kuwait_a = cv_generated_applicant("pa01", destination_country="Kuwait")
		saudi_b = cv_generated_applicant("pa02", destination_country="Saudi Arabia")
		contractor = make_contractor("pa01", country="Kuwait")

		frappe.set_user(contractor.user)
		names = {row["name"] for row in list_portal_candidates()}
		self.assertIn(kuwait_a.name, names)
		self.assertNotIn(saudi_b.name, names)

	def test_select_candidate_locks_applicant_and_creates_placement(self):
		applicant = cv_generated_applicant("pa03", destination_country="Kuwait")
		contractor = make_contractor("pa03", country="Kuwait")

		frappe.set_user(contractor.user)
		result = select_candidate(applicant.name)
		self.assertEqual(result["status"], "Selected")
		self.assertEqual(result["contractor"], contractor.name)

		applicant.reload()
		self.assertEqual(applicant.active_placement, result["name"])

	def test_selected_candidate_disappears_from_own_and_other_catalogs(self):
		applicant = cv_generated_applicant("pa04", destination_country="Kuwait")
		buyer = make_contractor("pa04a", country="Kuwait")
		bystander = make_contractor("pa04b", country="Kuwait")

		frappe.set_user(buyer.user)
		select_candidate(applicant.name)

		frappe.set_user(buyer.user)
		self.assertNotIn(applicant.name, {r["name"] for r in list_portal_candidates()})

		frappe.set_user(bystander.user)
		self.assertNotIn(applicant.name, {r["name"] for r in list_portal_candidates()})

	def test_second_agency_cannot_select_already_selected_candidate(self):
		applicant = cv_generated_applicant("pa05", destination_country="Kuwait")
		first = make_contractor("pa05a", country="Kuwait")
		second = make_contractor("pa05b", country="Kuwait")

		frappe.set_user(first.user)
		select_candidate(applicant.name)

		frappe.set_user(second.user)
		with self.assertRaises(frappe.ValidationError):
			select_candidate(applicant.name)

	def test_contractor_cannot_select_across_countries(self):
		applicant = cv_generated_applicant("pa06", destination_country="Kuwait")
		wrong_country_contractor = make_contractor("pa06", country="Saudi Arabia")

		frappe.set_user(wrong_country_contractor.user)
		with self.assertRaises(frappe.PermissionError):
			select_candidate(applicant.name)

	def test_non_foreign_agency_user_cannot_browse_portal(self):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "not-an-agency@example.com",
				"first_name": "Not Agency",
				"send_welcome_email": 0,
				"roles": [{"role": "Recruitment/Intake"}],
			}
		).insert(ignore_permissions=True)

		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			list_portal_candidates()
