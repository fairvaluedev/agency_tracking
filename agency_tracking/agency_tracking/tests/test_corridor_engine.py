# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.corridor_engine import (
	get_corridor_steps,
	get_first_step_type,
	get_next_step_type,
	is_last_step,
)
from agency_tracking.install import CORRIDORS, create_corridors


class TestCorridorEngine(FrappeTestCase):
	def test_saudi_corridor_seeded_and_ordered(self):
		create_corridors()
		steps = get_corridor_steps("Saudi Arabia")
		self.assertEqual(
			[s["step_type"] for s in steps], ["LMIS Clearance", "Taeshir", "Injaz", "Embassy/Wakala"]
		)

	def test_kuwait_corridor_seeded_and_ordered(self):
		create_corridors()
		steps = get_corridor_steps("Kuwait")
		self.assertEqual(
			[s["step_type"] for s in steps],
			["LMIS Police Clearance", "Telesign", "Kuwait Embassy", "LMIS Work Permit"],
		)

	def test_unconfigured_country_throws(self):
		with self.assertRaises(frappe.ValidationError):
			get_corridor_steps("Antarctica")

	def test_next_and_last_step_saudi(self):
		create_corridors()
		self.assertEqual(get_first_step_type("Saudi Arabia"), "LMIS Clearance")
		self.assertEqual(get_next_step_type("Saudi Arabia", 1), "Taeshir")
		self.assertEqual(get_next_step_type("Saudi Arabia", 4), None)
		self.assertTrue(is_last_step("Saudi Arabia", 4))
		self.assertFalse(is_last_step("Saudi Arabia", 1))

	def test_new_corridor_added_as_pure_data_no_code_change(self):
		"""Part A.3's central claim: adding a destination is a data change, not code. Proof:
		define a throwaway corridor here, in test data only, and confirm the exact same
		corridor_engine functions used above for Saudi/Kuwait work on it unmodified."""
		frappe.get_doc(
			{
				"doctype": "Corridor Definition",
				"destination_country": "United Arab Emirates",
				"steps": [
					{"step_type": "Dubai Labour Contract Attestation", "sequence_order": 1, "is_mandatory": 1},
					{"step_type": "Dubai Medical Fitness Test", "sequence_order": 2, "is_mandatory": 1},
					{"step_type": "Dubai Visa Stamping", "sequence_order": 3, "is_mandatory": 0},
				],
			}
		).insert(ignore_permissions=True)

		steps = get_corridor_steps("United Arab Emirates")
		self.assertEqual(len(steps), 3)
		self.assertEqual(get_first_step_type("United Arab Emirates"), "Dubai Labour Contract Attestation")
		self.assertEqual(get_next_step_type("United Arab Emirates", 2), "Dubai Visa Stamping")
		self.assertTrue(is_last_step("United Arab Emirates", 3))
		self.assertFalse(steps[2]["is_mandatory"])
