# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.doctype.placement.test_placement import (
	make_contractor,
	registered_applicant,
)
from agency_tracking.agency_tracking.tests.test_state_machine import (
	complete_all_clearance_steps,
	selected_placement,
)
from agency_tracking.clearance_api import complete_clearance_step
from agency_tracking.clearance_engine import get_lmis_officer
from agency_tracking.state_machine import transition


def saudi_selected_placement(tag):
	applicant = registered_applicant(
		tag, entry_track="Muayena", destination_country="Saudi Arabia"
	)
	contractor = make_contractor(tag, country="Saudi Arabia")
	placement = frappe.get_doc(
		{
			"doctype": "Placement",
			"applicant": applicant.name,
			"contractor": contractor.name,
			"destination_country": "Saudi Arabia",
			"status": "Selected",
			# Selected -> Processing gate (2026-08-29 medical checkpoint) -- set FIT up front so
			# every existing fixture that advances straight to Processing keeps working.
			"medical_selected_status": "FIT",
		}
	).insert(ignore_permissions=True)
	frappe.db.set_value("Applicant", applicant.name, "active_placement", placement.name)
	return placement


class TestClearanceEngine(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_processing_creates_steps_matching_corridor(self):
		placement = saudi_selected_placement("ce01")
		transition(placement, "Processing")
		steps = frappe.get_all(
			"Clearance Step",
			filters={"placement": placement.name},
			fields=["step_type", "sequence_order"],
			order_by="sequence_order asc",
		)
		self.assertEqual(
			[s.step_type for s in steps], ["LMIS Clearance", "Taeshir", "Embassy"]
		)

	def test_auto_assignment_broadcasts_todo_to_every_role_holder(self):
		"""2026-08-29: the six country+step roles replaced per-row Step Officer Mapping
		assignment for their step types -- every holder of "Saudi LMIS" gets a ToDo, not a
		single default_officer."""
		officer = frappe.get_doc(
			{
				"doctype": "User",
				"email": "ce-lmis-officer@example.com",
				"first_name": "LMIS Officer",
				"send_welcome_email": 0,
				"roles": [{"role": "Saudi LMIS"}],
			}
		).insert(ignore_permissions=True)

		placement = saudi_selected_placement("ce02")
		transition(placement, "Processing")

		lmis_step = frappe.db.get_value(
			"Clearance Step", {"placement": placement.name, "step_type": "LMIS Clearance"}, "name"
		)
		allocated_to = frappe.db.get_value(
			"ToDo", {"reference_type": "Clearance Step", "reference_name": lmis_step, "status": "Open"}, "allocated_to"
		)
		self.assertEqual(allocated_to, officer.name)
		self.assertEqual(get_lmis_officer(placement), officer.name)

	def test_lmis_officer_auto_chains_to_ticketing_and_departure(self):
		officer = frappe.get_doc(
			{
				"doctype": "User",
				"email": "ce-chain-officer@example.com",
				"first_name": "Chain Officer",
				"send_welcome_email": 0,
				"roles": [{"role": "Clearance Officer"}],
			}
		).insert(ignore_permissions=True)

		placement = saudi_selected_placement("ce03")
		transition(placement, "Processing")

		lmis_step = frappe.db.get_value(
			"Clearance Step", {"placement": placement.name, "step_type": "LMIS Clearance"}, "name"
		)
		from agency_tracking.clearance_engine import assign_clearance_step

		assign_clearance_step(lmis_step, officer.name)

		complete_all_clearance_steps(placement.name)

		transition(placement, "Stamped")
		ticket_todo = frappe.db.exists(
			"ToDo", {"reference_type": "Placement", "reference_name": placement.name, "allocated_to": officer.name}
		)
		self.assertTrue(ticket_todo)

		transition(placement, "Ticketed")
		departure_todos = frappe.get_all(
			"ToDo",
			filters={"reference_type": "Placement", "reference_name": placement.name, "allocated_to": officer.name},
		)
		# One from Stamped (ticketing) + one from Ticketed (departure).
		self.assertEqual(len(departure_todos), 2)

	def test_stamped_blocked_until_all_mandatory_steps_complete(self):
		placement = saudi_selected_placement("ce04")
		transition(placement, "Processing")
		with self.assertRaises(frappe.ValidationError):
			transition(placement, "Stamped")

	def test_stamped_succeeds_once_all_mandatory_steps_complete(self):
		placement = saudi_selected_placement("ce05")
		transition(placement, "Processing")
		complete_all_clearance_steps(placement.name)
		transition(placement, "Stamped")
		self.assertEqual(placement.status, "Stamped")

	def test_full_lifecycle_selected_to_departed(self):
		placement = saudi_selected_placement("ce06")
		transition(placement, "Processing")
		complete_all_clearance_steps(placement.name)
		transition(placement, "Stamped")
		transition(placement, "Ticketed")
		frappe.db.set_value("Placement", placement.name, "medical_2_status", "FIT")
		placement.reload()
		transition(placement, "Departed")
		self.assertEqual(placement.status, "Departed")
