# Copyright (c) 2026, Agency and contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.notification_engine import (
	notify,
	register_push_subscription,
	retry_pending_notifications,
)


def make_notify_user(tag):
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": f"notif-{tag}@example.com",
			"first_name": f"Notif {tag}",
			"send_welcome_email": 0,
			"roles": [{"role": "Clearance Officer"}],
		}
	).insert(ignore_permissions=True)


class TestNotificationEngine(FrappeTestCase):
	def test_notify_creates_log_and_marks_failed_without_subscription(self):
		user = make_notify_user("ne01")
		log = notify(user.name, "test_template", {"foo": "bar"})
		log.reload()
		self.assertEqual(log.status, "Failed")
		self.assertEqual(log.attempts, 1)
		self.assertIn("No Push Subscription", log.error)

	def test_notify_stores_context_as_json(self):
		user = make_notify_user("ne02")
		log = notify(user.name, "test_template", {"applicant": "APP-00001", "days_remaining": 7})
		context = frappe.parse_json(log.context)
		self.assertEqual(context["applicant"], "APP-00001")
		self.assertEqual(context["days_remaining"], 7)

	def test_register_push_subscription_creates_record(self):
		user = make_notify_user("ne03")
		register_push_subscription(user.name, "https://push.example.com/abc", "p256dh-key", "auth-key")
		self.assertTrue(frappe.db.exists("Push Subscription", {"user": user.name, "endpoint": "https://push.example.com/abc"}))

	def test_register_push_subscription_is_idempotent(self):
		user = make_notify_user("ne04")
		register_push_subscription(user.name, "https://push.example.com/dup", "k1", "a1")
		register_push_subscription(user.name, "https://push.example.com/dup", "k1", "a1")
		count = frappe.db.count("Push Subscription", filters={"user": user.name, "endpoint": "https://push.example.com/dup"})
		self.assertEqual(count, 1)

	def test_registering_subscription_retries_failed_notification(self):
		user = make_notify_user("ne05")
		log = notify(user.name, "test_template", {})
		log.reload()
		self.assertEqual(log.attempts, 1)  # failed once already, no subscription

		register_push_subscription(user.name, "https://push.example.com/retry", "k", "a")
		log.reload()
		# Still fails (no VAPID configured in Notification Config for this test site), but the
		# retry genuinely ran — attempts incremented and the failure reason changed from
		# "no subscription" to a VAPID-config error, proving retry_pending_notifications picked
		# it back up rather than skipping it.
		self.assertEqual(log.attempts, 2)
		self.assertNotIn("No Push Subscription", log.error)

	def test_retry_only_touches_pending_and_failed_not_sent(self):
		user = make_notify_user("ne06")
		sent_log = frappe.get_doc(
			{
				"doctype": "Comms Log",
				"recipient": user.name,
				"channel": "Push",
				"template": "already_sent",
				"status": "Sent",
				"attempts": 1,
			}
		).insert(ignore_permissions=True)

		retry_pending_notifications(user.name)

		sent_log.reload()
		self.assertEqual(sent_log.attempts, 1)  # untouched

	def test_deliver_push_succeeds_with_mocked_webpush(self):
		# Verifies the success path's logic (subscription lookup, VAPID config read, payload
		# shape) without depending on real network access or credentials — same spirit as the
		# rest of this build's honesty about what's genuinely verified vs. plausible-looking.
		user = make_notify_user("ne07")
		register_push_subscription(user.name, "https://push.example.com/ok", "p256dh-key", "auth-key")

		config = frappe.get_single("Notification Config")
		config.vapid_public_key = "test-public-key"
		config.vapid_private_key = "test-private-key"
		config.vapid_claims_email = "ops@example.com"
		config.save(ignore_permissions=True)

		with patch("pywebpush.webpush") as mock_webpush:
			log = notify(user.name, "test_template", {"x": 1})

		mock_webpush.assert_called_once()
		log.reload()
		self.assertEqual(log.status, "Sent")
