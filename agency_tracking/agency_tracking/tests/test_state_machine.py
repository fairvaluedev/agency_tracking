# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.doctype.placement.test_placement import (
	make_contractor,
	registered_applicant,
)
from agency_tracking.clearance_api import complete_clearance_step, stamp_embassy_step
from agency_tracking.state_machine import transition


def complete_all_clearance_steps(placement_name):
	"""Embassy steps go through their own Submitted -> Stamped outcome vocabulary
	(2026-08-29), not the generic complete_clearance_step -- everything else does."""
	for step in frappe.get_all(
		"Clearance Step", filters={"placement": placement_name}, fields=["name", "step_type"]
	):
		if step.step_type in ("Embassy", "Kuwait Embassy"):
			stamp_embassy_step(step.name)
		else:
			complete_clearance_step(step.name)


def selected_placement(tag):
	applicant = registered_applicant(tag, entry_track="Muayena", destination_country="Kuwait")
	contractor = make_contractor(tag, country="Kuwait")
	placement = frappe.get_doc(
		{
			"doctype": "Placement",
			"applicant": applicant.name,
			"contractor": contractor.name,
			"destination_country": "Kuwait",
			"status": "Selected",
			"medical_selected_status": "FIT",
		}
	).insert(ignore_permissions=True)
	frappe.db.set_value("Applicant", applicant.name, "active_placement", placement.name)
	return placement


def ticketed_placement(tag):
	placement = selected_placement(tag)
	transition(placement, "Processing")
	# Step 7 made Processing->Stamped a real gate (all mandatory Clearance Steps complete) —
	# clear the corridor's steps before advancing, same as clearance_engine tests do.
	complete_all_clearance_steps(placement.name)
	transition(placement, "Stamped")
	transition(placement, "Ticketed")
	return placement


class TestStateMachine(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_ungated_transition_logs_process_event(self):
		placement = selected_placement("sm01")
		transition(placement, "Processing")

		events = frappe.get_all(
			"Process Event",
			filters={"reference_doctype": "Placement", "reference_name": placement.name},
			fields=["event_type", "from_status", "to_status", "actor"],
		)
		self.assertEqual(len(events), 1)
		self.assertEqual(events[0]["event_type"], "Transition")
		self.assertEqual(events[0]["from_status"], "Selected")
		self.assertEqual(events[0]["to_status"], "Processing")
		self.assertEqual(events[0]["actor"], "Administrator")

	def test_medical_2_gate_blocks_departure(self):
		placement = ticketed_placement("sm02")
		with self.assertRaises(frappe.ValidationError):
			transition(placement, "Departed")

	def test_medical_2_gate_passes_when_fit(self):
		placement = ticketed_placement("sm03")
		frappe.db.set_value("Placement", placement.name, "medical_2_status", "FIT")
		placement.reload()
		transition(placement, "Departed")
		self.assertEqual(placement.status, "Departed")

	def test_override_requires_reason(self):
		placement = ticketed_placement("sm04")
		with self.assertRaises(frappe.ValidationError):
			transition(placement, "Departed", override=True, override_reason="")

	def test_override_requires_manager_role(self):
		placement = ticketed_placement("sm05")
		non_manager = frappe.get_doc(
			{
				"doctype": "User",
				"email": "not-a-manager@example.com",
				"first_name": "Not Manager",
				"send_welcome_email": 0,
				"roles": [{"role": "Registrar"}],
			}
		).insert(ignore_permissions=True)

		frappe.set_user(non_manager.name)
		with self.assertRaises(frappe.PermissionError):
			transition(placement, "Departed", override=True, override_reason="Family emergency, medical waived")

	def test_override_by_manager_succeeds_and_logs_override_event(self):
		placement = ticketed_placement("sm06")
		manager = frappe.get_doc(
			{
				"doctype": "User",
				"email": "a-manager@example.com",
				"first_name": "A Manager",
				"send_welcome_email": 0,
				"roles": [{"role": "Manager"}],
			}
		).insert(ignore_permissions=True)

		frappe.set_user(manager.name)
		transition(placement, "Departed", override=True, override_reason="Cleared by phone, paperwork to follow")
		self.assertEqual(placement.status, "Departed")

		events = frappe.get_all(
			"Process Event",
			filters={
				"reference_doctype": "Placement",
				"reference_name": placement.name,
				"event_type": "Override",
			},
			fields=["remarks", "actor"],
		)
		self.assertEqual(len(events), 1)
		self.assertEqual(events[0]["actor"], manager.name)
		self.assertIn("Cleared by phone", events[0]["remarks"])

	def test_disallowed_edge_still_blocked_regardless_of_override(self):
		placement = selected_placement("sm07")
		with self.assertRaises(frappe.ValidationError):
			transition(placement, "Departed", override=True, override_reason="Skip everything")
