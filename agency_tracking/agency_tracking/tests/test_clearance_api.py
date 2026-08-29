# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.tests.test_clearance_engine import saudi_selected_placement
from agency_tracking.clearance_api import complete_clearance_step, reassign_clearance_step, start_clearance_step
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
