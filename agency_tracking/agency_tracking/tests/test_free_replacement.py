# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.doctype.placement.test_placement import make_contractor
from agency_tracking.agency_tracking.tests.test_finance_engine import departed_placement
from agency_tracking.agency_tracking.tests.test_portal_api import cv_generated_applicant
from agency_tracking.complaint_api import acknowledge_complaint, create_complaint, resolve_complaint
from agency_tracking.finance_engine import accrue_commission
from agency_tracking.portal_api import select_candidate


def approved_free_replacement_complaint(tag, contractor):
	# departed_placement(tag) creates its own throwaway Contractor internally (via
	# saudi_selected_placement -> make_contractor(tag, ...)) — use a distinct sub-tag so it
	# never collides with the caller's own `contractor` fixture (same tag would mean two
	# make_contractor() calls both trying to create "agency-{tag}@example.com").
	placement = departed_placement(f"{tag}-orig")
	frappe.db.set_value("Placement", placement.name, "contractor", contractor.name)
	complaint = create_complaint(placement.name, "Worker returned within window", "Returned")
	acknowledge_complaint(complaint["name"])
	return resolve_complaint(complaint["name"], "Returned - Free Replacement Required")


class TestFreeReplacement(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_select_candidate_as_free_replacement_skips_billing(self):
		contractor = make_contractor("fr01", country="Saudi Arabia")
		complaint = approved_free_replacement_complaint("fr01", contractor)

		replacement_candidate = cv_generated_applicant("fr01b", destination_country="Saudi Arabia")
		frappe.set_user(contractor.user)
		placement = select_candidate(replacement_candidate.name, free_replacement_for_complaint=complaint["name"])
		self.assertTrue(placement["is_free_replacement"])
		self.assertEqual(placement["free_replacement_for_complaint"], complaint["name"])

		frappe.set_user("Administrator")
		placement_doc = frappe.get_doc("Placement", placement["name"])
		txn = accrue_commission(placement_doc)
		self.assertIsNone(txn)
		self.assertFalse(
			frappe.db.exists(
				"Applicant Transaction", {"placement": placement["name"], "transaction_type": "Commission"}
			)
		)

	def test_free_replacement_credit_can_only_be_used_once(self):
		contractor = make_contractor("fr02", country="Saudi Arabia")
		complaint = approved_free_replacement_complaint("fr02", contractor)

		first_candidate = cv_generated_applicant("fr02a", destination_country="Saudi Arabia")
		second_candidate = cv_generated_applicant("fr02b", destination_country="Saudi Arabia")

		frappe.set_user(contractor.user)
		select_candidate(first_candidate.name, free_replacement_for_complaint=complaint["name"])
		with self.assertRaises(frappe.ValidationError):
			select_candidate(second_candidate.name, free_replacement_for_complaint=complaint["name"])

	def test_free_replacement_credit_cannot_be_used_by_a_different_contractor(self):
		owner = make_contractor("fr03owner", country="Saudi Arabia")
		outsider = make_contractor("fr03out", country="Saudi Arabia")
		complaint = approved_free_replacement_complaint("fr03", owner)

		candidate = cv_generated_applicant("fr03b", destination_country="Saudi Arabia")
		frappe.set_user(outsider.user)
		with self.assertRaises(frappe.PermissionError):
			select_candidate(candidate.name, free_replacement_for_complaint=complaint["name"])

	def test_normal_selection_is_not_flagged_free(self):
		contractor = make_contractor("fr04", country="Saudi Arabia")
		candidate = cv_generated_applicant("fr04b", destination_country="Saudi Arabia")

		frappe.set_user(contractor.user)
		placement = select_candidate(candidate.name)
		self.assertFalse(placement["is_free_replacement"])
		self.assertFalse(placement["free_replacement_for_complaint"])
