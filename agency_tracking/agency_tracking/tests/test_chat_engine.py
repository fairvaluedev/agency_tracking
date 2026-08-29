# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.doctype.placement.test_placement import make_contractor
from agency_tracking.chat_engine import (
	get_or_create_agency_thread,
	get_or_create_internal_thread,
	route_agency_to_communication_manager,
	validate_thread_participants,
)


def make_comm_manager(tag):
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": f"ce-cm-{tag}@example.com",
			"first_name": f"CM {tag}",
			"send_welcome_email": 0,
			"roles": [{"role": "Communication Manager"}],
		}
	).insert(ignore_permissions=True)


def make_staff(tag, role="Registrar"):
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": f"ce-staff-{tag}@example.com",
			"first_name": f"Staff {tag}",
			"send_welcome_email": 0,
			"roles": [{"role": role}],
		}
	).insert(ignore_permissions=True)


class TestChatEngine(FrappeTestCase):
	def test_agency_cannot_message_another_agency(self):
		agency_a = make_contractor("ce01a", country="Kuwait")
		agency_b = make_contractor("ce01b", country="Kuwait")
		with self.assertRaises(frappe.ValidationError):
			validate_thread_participants(agency_a.user, agency_b.user)

	def test_agency_can_only_message_communication_manager_or_admin(self):
		agency = make_contractor("ce02", country="Kuwait")
		staff = make_staff("ce02")
		with self.assertRaises(frappe.ValidationError):
			validate_thread_participants(agency.user, staff.name)

	def test_agency_can_message_communication_manager(self):
		agency = make_contractor("ce03", country="Kuwait")
		manager = make_comm_manager("ce03")
		validate_thread_participants(agency.user, manager.name)  # should not raise

	def test_agency_can_message_admin(self):
		agency = make_contractor("ce04", country="Kuwait")
		validate_thread_participants(agency.user, "Administrator")  # should not raise

	def test_internal_staff_to_staff_unrestricted(self):
		staff_a = make_staff("ce05a", "Registrar")
		staff_b = make_staff("ce05b", "Clearance Officer")
		validate_thread_participants(staff_a.name, staff_b.name)  # should not raise

	def test_per_contractor_routing_used_when_configured(self):
		manager = make_comm_manager("ce06")
		contractor = make_contractor("ce06", country="Kuwait")
		contractor.communication_manager = manager.name
		contractor.save(ignore_permissions=True)

		self.assertEqual(route_agency_to_communication_manager(contractor.name), manager.name)

	def test_round_robin_used_when_not_configured(self):
		make_comm_manager("ce07a")
		make_comm_manager("ce07b")
		contractor = make_contractor("ce07", country="Kuwait")
		result = route_agency_to_communication_manager(contractor.name)
		self.assertTrue(frappe.db.exists("User", result))
		self.assertIn("Communication Manager", frappe.get_roles(result))

	def test_routing_throws_when_no_communication_manager_exists_at_all(self):
		# A fresh site with zero Communication Manager users configured — plausible early-days
		# state, must fail clearly rather than silently routing to nobody. Deleting the role
		# assignments is global/shared state, not scoped to this test's own fixtures like every
		# other test in this suite — restore it via addCleanup (runs even on assertion failure)
		# rather than relying on alphabetical test-ordering to keep this from breaking sibling
		# tests, the same class of bug already hit twice before (Steps 7 and 9).
		existing = frappe.get_all(
			"Has Role", filters={"role": "Communication Manager", "parenttype": "User"}, fields=["parent"]
		)
		frappe.db.delete("Has Role", {"role": "Communication Manager"})

		def _restore():
			for row in existing:
				if not frappe.db.exists("Has Role", {"parent": row.parent, "role": "Communication Manager"}):
					frappe.get_doc(
						{
							"doctype": "Has Role",
							"parent": row.parent,
							"parenttype": "User",
							"parentfield": "roles",
							"role": "Communication Manager",
						}
					).insert(ignore_permissions=True)

		self.addCleanup(_restore)

		contractor = make_contractor("ce08", country="Kuwait")
		with self.assertRaises(frappe.ValidationError):
			route_agency_to_communication_manager(contractor.name)

	def test_get_or_create_agency_thread_reopens_existing(self):
		make_comm_manager("ce09")
		contractor = make_contractor("ce09", country="Kuwait")
		first = get_or_create_agency_thread(contractor.name)
		second = get_or_create_agency_thread(contractor.name)
		self.assertEqual(first.name, second.name)

	def test_get_or_create_internal_thread_reopens_existing(self):
		staff_a = make_staff("ce10a")
		staff_b = make_staff("ce10b", "Clearance Officer")
		first = get_or_create_internal_thread(staff_a.name, staff_b.name)
		second = get_or_create_internal_thread(staff_a.name, staff_b.name)
		self.assertEqual(first.name, second.name)

	def test_get_or_create_internal_thread_distinct_per_context(self):
		staff_a = make_staff("ce11a")
		staff_b = make_staff("ce11b", "Clearance Officer")
		general_thread = get_or_create_internal_thread(staff_a.name, staff_b.name)
		placement_thread = get_or_create_internal_thread(
			staff_a.name, staff_b.name, context_type="Placement", context_reference="PLM-FAKE"
		)
		self.assertNotEqual(general_thread.name, placement_thread.name)
