# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCorridorDefinition(FrappeTestCase):
	def test_duplicate_sequence_order_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Corridor Definition",
					"destination_country": "Qatar",
					"steps": [
						{"step_type": "LMIS Clearance", "sequence_order": 1, "is_mandatory": 1},
						{"step_type": "Embassy", "sequence_order": 1, "is_mandatory": 1},
					],
				}
			).insert(ignore_permissions=True)

	def test_duplicate_step_type_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Corridor Definition",
					"destination_country": "Oman",
					"steps": [
						{"step_type": "LMIS Clearance", "sequence_order": 1, "is_mandatory": 1},
						{"step_type": "LMIS Clearance", "sequence_order": 2, "is_mandatory": 1},
					],
				}
			).insert(ignore_permissions=True)

	def test_one_corridor_per_country(self):
		frappe.get_doc(
			{
				"doctype": "Corridor Definition",
				"destination_country": "Bahrain",
				"steps": [{"step_type": "LMIS Clearance", "sequence_order": 1, "is_mandatory": 1}],
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc(
				{
					"doctype": "Corridor Definition",
					"destination_country": "Bahrain",
					"steps": [{"step_type": "Embassy", "sequence_order": 1, "is_mandatory": 1}],
				}
			).insert(ignore_permissions=True)
