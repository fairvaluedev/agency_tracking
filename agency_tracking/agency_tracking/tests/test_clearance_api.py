# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.tests.test_clearance_engine import saudi_selected_placement
from agency_tracking.agency_tracking.tests.test_finance_engine import departed_placement
from agency_tracking.clearance_api import (
	complete_clearance_step,
	reassign_clearance_step,
	reject_embassy_step,
	stamp_embassy_step,
	start_clearance_step,
)
from agency_tracking.clearance_engine import assign_clearance_step
from agency_tracking.state_machine import transition


class TestClearanceAPI(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def _first_step(self, placement):
		return frappe.get_all(
			"Clearance Step", filters={"placement": placement.name}, order_by="sequence_order asc", limit=1
		)[0].name

	def test_assigned_officer_can_start_and_complete(self):
		placement = saudi_selected_placement("ca01")
		transition(placement, "Processing")
		step_name = self._first_step(placement)

		officer = frappe.get_doc(
			{
				"doctype": "User",
				"email": "ca-officer@example.com",
				"first_name": "CA Officer",
				"send_welcome_email": 0,
				"roles": [{"role": "Clearance Officer"}],
			}
		).insert(ignore_permissions=True)
		assign_clearance_step(step_name, officer.name)

		frappe.set_user(officer.name)
		start_clearance_step(step_name)
		result = complete_clearance_step(step_name, reference_no="REF-123")
		self.assertEqual(result["status"], "Issued")
		self.assertEqual(result["reference_no"], "REF-123")

	def test_unassigned_officer_cannot_complete(self):
		placement = saudi_selected_placement("ca02")
		transition(placement, "Processing")
		step_name = self._first_step(placement)

		assigned = frappe.get_doc(
			{
				"doctype": "User",
				"email": "ca-assigned@example.com",
				"first_name": "CA Assigned",
				"send_welcome_email": 0,
				"roles": [{"role": "Clearance Officer"}],
			}
		).insert(ignore_permissions=True)
		bystander = frappe.get_doc(
			{
				"doctype": "User",
				"email": "ca-bystander@example.com",
				"first_name": "CA Bystander",
				"send_welcome_email": 0,
				"roles": [{"role": "Clearance Officer"}],
			}
		).insert(ignore_permissions=True)
		assign_clearance_step(step_name, assigned.name)

		frappe.set_user(bystander.name)
		with self.assertRaises(frappe.PermissionError):
			complete_clearance_step(step_name)

	def test_manager_can_complete_any_step(self):
		placement = saudi_selected_placement("ca03")
		transition(placement, "Processing")
		step_name = self._first_step(placement)

		manager = frappe.get_doc(
			{
				"doctype": "User",
				"email": "ca-manager@example.com",
				"first_name": "CA Manager",
				"send_welcome_email": 0,
				"roles": [{"role": "Manager"}],
			}
		).insert(ignore_permissions=True)

		frappe.set_user(manager.name)
		result = complete_clearance_step(step_name)
		self.assertEqual(result["status"], "Issued")

	def test_reassignment_restricted_to_manager(self):
		placement = saudi_selected_placement("ca04")
		transition(placement, "Processing")
		step_name = self._first_step(placement)

		new_officer = frappe.get_doc(
			{
				"doctype": "User",
				"email": "ca-new-officer@example.com",
				"first_name": "CA New",
				"send_welcome_email": 0,
				"roles": [{"role": "Clearance Officer"}],
			}
		).insert(ignore_permissions=True)
		non_manager = frappe.get_doc(
			{
				"doctype": "User",
				"email": "ca-non-manager@example.com",
				"first_name": "CA Non Manager",
				"send_welcome_email": 0,
				"roles": [{"role": "Clearance Officer"}],
			}
		).insert(ignore_permissions=True)

		frappe.set_user(non_manager.name)
		with self.assertRaises(frappe.PermissionError):
			reassign_clearance_step(step_name, new_officer.name)

		frappe.set_user("Administrator")
		result = reassign_clearance_step(step_name, new_officer.name)
		self.assertEqual(result["assigned_to"], new_officer.name)

	def test_complete_clearance_step_blocked_once_already_issued(self):
		# cc2 QA pass, finding NEW-3's bug class: no clearance-step action checked whether the
		# step was already in a terminal state before overwriting it.
		placement = saudi_selected_placement("ca05")
		transition(placement, "Processing")
		step_name = self._first_step(placement)
		complete_clearance_step(step_name)
		self.assertEqual(frappe.db.get_value("Clearance Step", step_name, "status"), "Issued")

		with self.assertRaises(frappe.ValidationError):
			complete_clearance_step(step_name)

	def test_reject_embassy_step_blocked_once_placement_departed(self):
		# cc2 QA pass, finding NEW-3 exact repro: a Kuwait/Saudi Embassy user could flip an
		# already-Stamped step on an already-Departed Placement back to Rejected, producing a
		# self-contradictory record (Departed placement, Rejected corridor step).
		placement = departed_placement("ca06")
		embassy_step = frappe.db.get_value(
			"Clearance Step", {"placement": placement.name, "step_type": "Embassy"}, "name"
		)
		self.assertEqual(frappe.db.get_value("Clearance Step", embassy_step, "status"), "Stamped")

		with self.assertRaises(frappe.ValidationError):
			reject_embassy_step(embassy_step, "QA test - probing terminal-state guard")

		self.assertEqual(frappe.db.get_value("Clearance Step", embassy_step, "status"), "Stamped")
		self.assertEqual(frappe.db.get_value("Placement", placement.name, "status"), "Departed")

	def test_stamp_embassy_step_blocked_once_already_stamped(self):
		placement = departed_placement("ca07")
		embassy_step = frappe.db.get_value(
			"Clearance Step", {"placement": placement.name, "step_type": "Embassy"}, "name"
		)
		with self.assertRaises(frappe.ValidationError):
			stamp_embassy_step(embassy_step)
