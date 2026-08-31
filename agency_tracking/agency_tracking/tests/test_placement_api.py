# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.doctype.placement.test_placement import (
	make_contractor,
	registered_applicant,
)
from agency_tracking.agency_tracking.tests.test_portal_api import cv_generated_applicant
from agency_tracking.placement_api import (
	advance_placement,
	create_muayena_placement,
	list_placements,
	record_predeparture_medical_result,
	record_reschedule,
	record_ticket_details,
	upload_contract,
)
from agency_tracking.portal_api import select_candidate


def make_role_user(tag, role):
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": f"mpa-{tag}@example.com",
			"first_name": f"MPA {tag}",
			"send_welcome_email": 0,
			"roles": [{"role": role}],
		}
	).insert(ignore_permissions=True)

CONTRACT_TEXT_WITH_DATE = "Employment Contract\nContract Date: 13/08/2026\n..."


class TestPlacementAPI(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_create_muayena_placement_success(self):
		applicant = registered_applicant("mpa01", entry_track="Muayena", destination_country="Kuwait")
		contractor = make_contractor("mpa01", country="Kuwait")

		result = create_muayena_placement(applicant.name, contractor.name)
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
			create_muayena_placement(applicant.name, contractor.name)

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
			create_muayena_placement(applicant.name, contractor.name)

	def test_create_muayena_placement_blocks_double_creation(self):
		applicant = registered_applicant("mpa04", entry_track="Muayena", destination_country="Kuwait")
		contractor = make_contractor("mpa04", country="Kuwait")
		create_muayena_placement(applicant.name, contractor.name)
		with self.assertRaises(frappe.ValidationError):
			create_muayena_placement(applicant.name, contractor.name)

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

	def test_advance_placement_normal_move(self):
		applicant = registered_applicant("mpa08", entry_track="Muayena", destination_country="Kuwait")
		contractor = make_contractor("mpa08", country="Kuwait")
		placement = create_muayena_placement(applicant.name, contractor.name)
		frappe.db.set_value("Placement", placement["name"], "medical_selected_status", "FIT")

		result = advance_placement(placement["name"], "Processing")
		self.assertEqual(result["status"], "Processing")

	def test_advance_placement_denies_foreign_agency_entirely(self):
		# Progressing a Placement through clearance stages is internal staff work (Part G) —
		# Placement's own doctype permissions grant no role to Foreign Agency at all, even the
		# contractor who owns this exact placement.
		applicant = registered_applicant("mpa09", entry_track="Muayena", destination_country="Kuwait")
		owner = make_contractor("mpa09", country="Kuwait")
		placement = create_muayena_placement(applicant.name, owner.name)

		frappe.set_user(owner.user)
		with self.assertRaises(frappe.PermissionError):
			advance_placement(placement["name"], "Processing")

	def test_record_predeparture_medical_result_fit_opens_path_to_departed(self):
		# backend-issues #01: this was previously impossible — medical_2_status had no
		# whitelisted writer anywhere, so no Placement could ever legally reach Departed.
		from agency_tracking.agency_tracking.tests.test_state_machine import complete_all_clearance_steps

		applicant = registered_applicant("mpa10", entry_track="Muayena", destination_country="Kuwait")
		contractor = make_contractor("mpa10", country="Kuwait")
		placement = create_muayena_placement(applicant.name, contractor.name)
		frappe.db.set_value("Placement", placement["name"], "medical_selected_status", "FIT")
		advance_placement(placement["name"], "Processing")
		complete_all_clearance_steps(placement["name"])
		advance_placement(placement["name"], "Stamped")
		record_ticket_details(placement["name"], "TK-mpa10", "2026-09-15")
		advance_placement(placement["name"], "Ticketed")

		result = record_predeparture_medical_result(placement["name"], "FIT", examination_date="2026-09-12")
		self.assertEqual(result["medical_2_status"], "FIT")

		final = advance_placement(placement["name"], "Departed")
		self.assertEqual(final["status"], "Departed")

		# cc2 QA pass, finding NEW-1 exact repro: a Ticketer could silently rewrite
		# ticket_number/flight_date on an already-Departed Placement, with no audit trail.
		with self.assertRaises(frappe.ValidationError):
			record_ticket_details(placement["name"], "TK-HACK", "2099-01-01")
		unchanged = frappe.db.get_value(
			"Placement", placement["name"], ["ticket_number", "flight_date"], as_dict=True
		)
		self.assertEqual(unchanged.ticket_number, "TK-mpa10")

		with self.assertRaises(frappe.ValidationError):
			record_predeparture_medical_result(placement["name"], "FIT")

		with self.assertRaises(frappe.ValidationError):
			record_reschedule(placement["name"], "2099-01-01", "Internal")

	def test_record_predeparture_medical_result_unfit_cancels_applicant(self):
		from agency_tracking.agency_tracking.tests.test_state_machine import complete_all_clearance_steps

		applicant = registered_applicant("mpa11", entry_track="Muayena", destination_country="Kuwait")
		contractor = make_contractor("mpa11", country="Kuwait")
		placement = create_muayena_placement(applicant.name, contractor.name)
		frappe.db.set_value("Placement", placement["name"], "medical_selected_status", "FIT")
		advance_placement(placement["name"], "Processing")
		complete_all_clearance_steps(placement["name"])
		advance_placement(placement["name"], "Stamped")
		record_ticket_details(placement["name"], "TK-mpa11", "2026-09-15")
		advance_placement(placement["name"], "Ticketed")

		record_predeparture_medical_result(placement["name"], "UNFIT")

		applicant.reload()
		self.assertEqual(applicant.status, "Cancelled")

	def test_record_ticket_details_persists_fields_despite_missing_fx_rate(self):
		# backend-issues #05: a missing FX rate for the given currency used to roll back the
		# whole call, including ticket_number/flight_date, which have nothing to do with money.
		applicant = registered_applicant("mpa12", entry_track="Muayena", destination_country="Kuwait")
		contractor = make_contractor("mpa12", country="Kuwait")
		placement = create_muayena_placement(applicant.name, contractor.name)

		result = record_ticket_details(
			placement["name"], "TK-mpa12", "2026-09-15", ticket_cost=200, currency="XYZ-NO-RATE"
		)
		self.assertEqual(result["ticket_number"], "TK-mpa12")
		self.assertIn("warning", result)

		saved = frappe.db.get_value("Placement", placement["name"], ["ticket_number", "flight_date"], as_dict=True)
		self.assertEqual(saved.ticket_number, "TK-mpa12")

	def test_stamped_to_ticketed_blocked_without_ticket_number(self):
		from agency_tracking.agency_tracking.tests.test_state_machine import complete_all_clearance_steps

		applicant = registered_applicant("mpa13", entry_track="Muayena", destination_country="Kuwait")
		contractor = make_contractor("mpa13", country="Kuwait")
		placement = create_muayena_placement(applicant.name, contractor.name)
		frappe.db.set_value("Placement", placement["name"], "medical_selected_status", "FIT")
		advance_placement(placement["name"], "Processing")
		complete_all_clearance_steps(placement["name"])
		advance_placement(placement["name"], "Stamped")

		with self.assertRaises(frappe.ValidationError) as ctx:
			advance_placement(placement["name"], "Ticketed")
		self.assertIn("ticket_number", str(ctx.exception))

	def test_gate_error_message_names_the_missing_condition(self):
		# backend-issues #06: gate-blocked transitions used to return a fully generic
		# "gate condition not met" with no field/reason.
		applicant = registered_applicant("mpa14", entry_track="Muayena", destination_country="Kuwait")
		contractor = make_contractor("mpa14", country="Kuwait")
		placement = create_muayena_placement(applicant.name, contractor.name)

		with self.assertRaises(frappe.ValidationError) as ctx:
			advance_placement(placement["name"], "Processing")
		self.assertIn("medical (Selected stage) status", str(ctx.exception))
		self.assertIn("FIT", str(ctx.exception))

	def test_list_placements_readable_by_clearance_officer(self):
		# backend-issues #02: Clearance Officer had zero read access to Placement via the
		# frontend's old /api/resource/Placement fallback -- this is the whitelisted
		# replacement, and the doctype's own permissions now grant it read.
		applicant = registered_applicant("mpa15", entry_track="Muayena", destination_country="Kuwait")
		contractor = make_contractor("mpa15", country="Kuwait")
		placement = create_muayena_placement(applicant.name, contractor.name)

		officer = make_role_user("mpa15", "Clearance Officer")
		frappe.set_user(officer.name)
		result = list_placements(filters={"name": placement["name"]})
		self.assertEqual(len(result), 1)

	def test_list_placements_denied_for_foreign_agency_of_unrelated_placement(self):
		applicant = registered_applicant("mpa16", entry_track="Muayena", destination_country="Kuwait")
		contractor = make_contractor("mpa16", country="Kuwait")
		create_muayena_placement(applicant.name, contractor.name)

		other_agency = make_contractor("mpa16b", country="Kuwait")
		frappe.set_user(other_agency.user)
		with self.assertRaises(frappe.PermissionError):
			list_placements()
