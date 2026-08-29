# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.doctype.placement.test_placement import make_contractor
from agency_tracking.agency_tracking.tests.test_chat_engine import make_comm_manager, make_staff
from agency_tracking.chat_api import (
	add_participant,
	create_agency_thread,
	create_internal_thread,
	get_thread_messages,
	list_threads,
	mark_read,
	send_message,
)


class TestChatAPI(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_create_agency_thread_requires_linked_contractor(self):
		staff = make_staff("ca01")
		frappe.set_user(staff.name)
		with self.assertRaises(frappe.PermissionError):
			create_agency_thread()

	def test_create_agency_thread_routes_and_reopens(self):
		make_comm_manager("ca02")
		contractor = make_contractor("ca02", country="Kuwait")
		frappe.set_user(contractor.user)
		first = create_agency_thread()
		second = create_agency_thread()
		self.assertEqual(first["name"], second["name"])

	def test_send_message_requires_participant(self):
		make_comm_manager("ca03")
		contractor = make_contractor("ca03", country="Kuwait")
		frappe.set_user(contractor.user)
		thread = create_agency_thread()

		outsider = make_contractor("ca03out", country="Kuwait")
		frappe.set_user(outsider.user)
		with self.assertRaises(frappe.PermissionError):
			send_message(thread["name"], "Hello")

	def test_send_and_read_message_between_agency_and_manager(self):
		manager = make_comm_manager("ca04")
		contractor = make_contractor("ca04", country="Kuwait")
		# Pin explicitly rather than relying on round-robin — by this point in a shared test
		# run, many Communication Manager users exist from earlier tests, so round-robin could
		# legitimately route to any of them, not necessarily this test's own fixture. Same
		# class of shared-state assumption bug hit repeatedly before (Steps 7, 9, 11).
		contractor.communication_manager = manager.name
		contractor.save(ignore_permissions=True)

		frappe.set_user(contractor.user)
		thread = create_agency_thread()
		send_message(thread["name"], "When will the visa be ready?")

		frappe.set_user(manager.name)
		messages = get_thread_messages(thread["name"])
		self.assertEqual(len(messages), 1)
		self.assertEqual(messages[0]["message"], "When will the visa be ready?")

	def test_agency_cannot_see_another_agencys_thread(self):
		"""The addendum's explicit requirement: "this needs an explicit test, not just
		reliance on the participant filter." """
		make_comm_manager("ca05a")
		make_comm_manager("ca05b")
		agency_a = make_contractor("ca05a", country="Kuwait")
		agency_b = make_contractor("ca05b", country="Kuwait")

		frappe.set_user(agency_a.user)
		thread_a = create_agency_thread()

		frappe.set_user(agency_b.user)
		thread_b = create_agency_thread()

		threads_visible_to_b = list_threads()
		visible_names = {t["name"] for t in threads_visible_to_b}
		self.assertIn(thread_b["name"], visible_names)
		self.assertNotIn(thread_a["name"], visible_names)

		with self.assertRaises(frappe.PermissionError):
			get_thread_messages(thread_a["name"])
		with self.assertRaises(frappe.PermissionError):
			send_message(thread_a["name"], "Should never reach agency A's thread")

	def test_create_internal_thread_blocked_for_agency_users(self):
		contractor = make_contractor("ca06", country="Kuwait")
		staff = make_staff("ca06")
		frappe.set_user(contractor.user)
		with self.assertRaises(frappe.PermissionError):
			create_internal_thread(staff.name)

	def test_internal_thread_open_between_staff(self):
		staff_a = make_staff("ca07a")
		staff_b = make_staff("ca07b", "Clearance Officer")
		frappe.set_user(staff_a.name)
		thread = create_internal_thread(staff_b.name)
		send_message(thread["name"], "Can you push this LMIS clearance forward?")

		frappe.set_user(staff_b.name)
		messages = get_thread_messages(thread["name"])
		self.assertEqual(len(messages), 1)

	def test_mark_read_updates_own_participant_row_only(self):
		staff_a = make_staff("ca08a")
		staff_b = make_staff("ca08b", "Clearance Officer")
		frappe.set_user(staff_a.name)
		thread = create_internal_thread(staff_b.name)
		mark_read(thread["name"])

		doc = frappe.get_doc("Chat Thread", thread["name"])
		row_a = next(r for r in doc.participants if r.user == staff_a.name)
		row_b = next(r for r in doc.participants if r.user == staff_b.name)
		self.assertIsNotNone(row_a.last_read_at)
		self.assertIsNone(row_b.last_read_at)

	def test_cannot_add_participant_to_agency_thread(self):
		make_comm_manager("ca09")
		contractor = make_contractor("ca09", country="Kuwait")
		staff = make_staff("ca09")
		frappe.set_user(contractor.user)
		thread = create_agency_thread()

		with self.assertRaises(frappe.ValidationError):
			add_participant(thread["name"], staff.name)

	def test_can_add_participant_to_internal_thread(self):
		staff_a = make_staff("ca10a")
		staff_b = make_staff("ca10b", "Clearance Officer")
		staff_c = make_staff("ca10c", "Ticketer")
		frappe.set_user(staff_a.name)
		thread = create_internal_thread(staff_b.name)
		add_participant(thread["name"], staff_c.name)

		frappe.set_user(staff_c.name)
		messages = get_thread_messages(thread["name"])  # should not raise — now a participant
		self.assertEqual(messages, [])

	def test_mention_requires_read_permission_on_mentioned_record(self):
		from agency_tracking.agency_tracking.tests.test_clearance_engine import saudi_selected_placement

		staff_a = make_staff("ca11a")
		staff_b = make_staff("ca11b", "Clearance Officer")
		placement = saudi_selected_placement("ca11")

		frappe.set_user(staff_a.name)
		thread = create_internal_thread(staff_b.name)
		# Registrar has no doctype-level read permission on Placement (Part G scope
		# stops at Stage 3) — mentioning one should be rejected even though the thread itself
		# is fine.
		with self.assertRaises(frappe.PermissionError):
			send_message(thread["name"], "See this placement", mentioned_placement=placement.name)
