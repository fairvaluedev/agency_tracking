# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.tests.test_clearance_engine import saudi_selected_placement


def raw_complaint(placement, status="New", **overrides):
	data = {
		"doctype": "Complaint",
		"placement": placement.name,
		"contractor": placement.contractor,
		"raised_by": "Internal Staff",
		"worker_status_at_complaint": "Deployed",
		"description": "Worker allegedly not performing agreed duties.",
		"status": status,
	}
	data.update(overrides)
	return frappe.get_doc(data)


class TestComplaint(FrappeTestCase):
	def test_dismissed_requires_resolution_notes(self):
		placement = saudi_selected_placement("cp01")
		with self.assertRaises(frappe.ValidationError):
			raw_complaint(placement, status="Dismissed").insert(ignore_permissions=True)

	def test_dismissed_with_notes_succeeds(self):
		placement = saudi_selected_placement("cp02")
		doc = raw_complaint(placement, status="Dismissed", resolution_notes="No evidence found").insert(
			ignore_permissions=True
		)
		self.assertEqual(doc.status, "Dismissed")

	def test_new_complaint_does_not_require_resolution_notes(self):
		placement = saudi_selected_placement("cp03")
		doc = raw_complaint(placement).insert(ignore_permissions=True)
		self.assertEqual(doc.status, "New")
