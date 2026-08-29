# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.doctype.placement.test_placement import make_contractor
from agency_tracking.agency_tracking.tests.test_clearance_engine import saudi_selected_placement
from agency_tracking.agency_tracking.tests.test_finance_api import make_role_user
from agency_tracking.agency_tracking.tests.test_finance_engine import departed_placement
from agency_tracking.complaint_api import (
	acknowledge_complaint,
	create_complaint,
	list_unresolved_complaints,
	resolve_complaint,
)


class TestComplaintAPI(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_internal_staff_can_create_complaint(self):
		placement = saudi_selected_placement("ca01")
		staff = make_role_user("cmp01", "Registrar")
		frappe.set_user(staff.name)
		result = create_complaint(placement.name, "Worker unreachable", "Deployed")
		self.assertEqual(result["status"], "New")
		self.assertEqual(result["raised_by"], "Internal Staff")

	def test_owning_agency_can_create_complaint(self):
		placement = saudi_selected_placement("ca02")
		contractor = frappe.get_doc("Contractor", placement.contractor)
		frappe.set_user(contractor.user)
		result = create_complaint(placement.name, "Dispute over duties", "Deployed")
		self.assertEqual(result["raised_by"], "Foreign Agency")

	def test_other_agency_cannot_complain_about_someone_elses_placement(self):
		placement = saudi_selected_placement("ca03")
		outsider = make_contractor("ca03out", country="Saudi Arabia")
		frappe.set_user(outsider.user)
		with self.assertRaises(frappe.PermissionError):
			create_complaint(placement.name, "Not my placement", "Deployed")

	def test_role_without_recognized_staff_role_cannot_create(self):
		placement = saudi_selected_placement("ca04")
		nobody = frappe.get_doc(
			{
				"doctype": "User",
				"email": "cmp-nobody@example.com",
				"first_name": "Nobody",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		frappe.set_user(nobody.name)
		with self.assertRaises(frappe.PermissionError):
			create_complaint(placement.name, "test", "Deployed")

	def test_list_unresolved_sorted_oldest_first(self):
		placement = saudi_selected_placement("ca05")
		manager = make_role_user("cmp05", "Manager")
		frappe.set_user(manager.name)
		c1 = create_complaint(placement.name, "First", "Deployed")
		c2 = create_complaint(placement.name, "Second", "Deployed")
		# Acknowledgement itself is Complaint Manager/Admin only (Part A.5) — a plain Manager
		# can create a complaint (broader INTERNAL_STAFF_ROLES) but not move its status.
		frappe.set_user("Administrator")
		acknowledge_complaint(c1["name"])
		acknowledge_complaint(c2["name"])

		results = list_unresolved_complaints()
		names_in_order = [r["name"] for r in results if r["name"] in (c1["name"], c2["name"])]
		self.assertEqual(names_in_order, [c1["name"], c2["name"]])

	def test_acknowledge_requires_complaint_manager_role(self):
		placement = saudi_selected_placement("ca06")
		staff = make_role_user("cmp06", "Registrar")
		frappe.set_user(staff.name)
		complaint = create_complaint(placement.name, "test", "Deployed")

		with self.assertRaises(frappe.PermissionError):
			acknowledge_complaint(complaint["name"])

	def test_resolve_requires_complaint_manager_role(self):
		placement = saudi_selected_placement("ca07")
		frappe.set_user("Administrator")
		complaint = create_complaint(placement.name, "test", "Deployed")
		acknowledge_complaint(complaint["name"])

		staff = make_role_user("cmp07", "Registrar")
		frappe.set_user(staff.name)
		with self.assertRaises(frappe.PermissionError):
			resolve_complaint(complaint["name"], "Resolved")

	def test_dismiss_requires_reason(self):
		placement = saudi_selected_placement("ca08")
		complaint = create_complaint(placement.name, "test", "Deployed")
		acknowledge_complaint(complaint["name"])
		with self.assertRaises(frappe.ValidationError):
			resolve_complaint(complaint["name"], "Dismissed")

	def test_resolve_to_resolved_succeeds(self):
		placement = saudi_selected_placement("ca09")
		complaint = create_complaint(placement.name, "test", "Deployed")
		acknowledge_complaint(complaint["name"])
		result = resolve_complaint(complaint["name"], "Resolved")
		self.assertEqual(result["status"], "Resolved")
		self.assertEqual(result["resolved_by"], "Administrator")

	def test_resolve_to_escalated_succeeds(self):
		placement = saudi_selected_placement("ca10")
		complaint = create_complaint(placement.name, "test", "Deployed")
		acknowledge_complaint(complaint["name"])
		result = resolve_complaint(complaint["name"], "Escalated")
		self.assertEqual(result["status"], "Escalated")

	def test_free_replacement_blocked_before_departure(self):
		placement = saudi_selected_placement("ca11")
		complaint = create_complaint(placement.name, "Worker returned already", "Returned")
		acknowledge_complaint(complaint["name"])
		with self.assertRaises(frappe.ValidationError):
			resolve_complaint(complaint["name"], "Returned - Free Replacement Required")

	def test_free_replacement_succeeds_within_window(self):
		placement = departed_placement("ca12")
		complaint = create_complaint(placement.name, "Worker returned within 3 months", "Returned")
		acknowledge_complaint(complaint["name"])
		result = resolve_complaint(complaint["name"], "Returned - Free Replacement Required")
		self.assertEqual(result["status"], "Returned - Free Replacement Required")

	def test_free_replacement_blocked_outside_window_without_override(self):
		placement = departed_placement("ca13")
		frappe.db.set_value(
			"Placement", placement.name, "departed_on", frappe.utils.add_days(frappe.utils.now_datetime(), -120)
		)
		complaint = create_complaint(placement.name, "Worker returned late", "Returned")
		acknowledge_complaint(complaint["name"])
		with self.assertRaises(frappe.ValidationError):
			resolve_complaint(complaint["name"], "Returned - Free Replacement Required")

	def test_free_replacement_outside_window_allowed_via_manager_override(self):
		placement = departed_placement("ca14")
		frappe.db.set_value(
			"Placement", placement.name, "departed_on", frappe.utils.add_days(frappe.utils.now_datetime(), -120)
		)
		complaint = create_complaint(placement.name, "Late return, exceptional case", "Returned")
		acknowledge_complaint(complaint["name"])

		# A plain Manager (no Complaint Manager role) can override — Manager Override is a
		# Manager-level power throughout this build, not delegated to domain-specific roles.
		manager = make_role_user("cmp14", "Manager")
		frappe.set_user(manager.name)
		result = resolve_complaint(
			complaint["name"],
			"Returned - Free Replacement Required",
			override_reason="Manager approved exception outside window",
		)
		self.assertEqual(result["status"], "Returned - Free Replacement Required")
