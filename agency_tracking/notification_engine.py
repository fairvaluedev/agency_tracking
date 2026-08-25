# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part E: "One delivery pipeline serves three features (assignment alerts, chat, watchdog
# alerts)." notify() is transcribed directly from Part E's pseudocode. Delivery itself
# (_deliver_push / _deliver_whatsapp) calls real external services (pywebpush, WhatsApp Cloud
# API) but — same honesty standard as fetch_daily_fx_rates in Step 8 — neither has been
# exercised against live credentials/a real subscribed browser in this build. What's fully
# verified is the part that's actually load-bearing for correctness: the queue never loses a
# notification, retries pick up exactly the Pending/Failed rows, and delivery failures never
# raise into the caller.
#
# notify() is deliberately NOT whitelisted — it's an internal building block called by
# clearance_engine (assignment alerts), watchdogs.py, and (Step 12) chat, never directly by a
# client. Whitelisting it would let any authenticated user spam-notify any other user by name;
# the only client-facing surface for this pipeline is notification_api.py's
# register_push_subscription (a user subscribing their own browser) and the manual watchdog
# triggers.

import frappe
from frappe.utils import now_datetime


def notify(user, template, context, channel="Push"):
	log = frappe.get_doc(
		{
			"doctype": "Comms Log",
			"recipient": user,
			"channel": channel,
			"template": template,
			"context": frappe.as_json(context) if not isinstance(context, str) else context,
			"status": "Pending",
		}
	).insert(ignore_permissions=True)
	attempt_push_delivery(log)
	return log


def attempt_push_delivery(log):
	"""Best-effort, never raises — delivery failures are retried on next login and on new
	Push Subscription registration (Part E), not by crashing whatever triggered the notify()
	call (an assignment, a watchdog sweep, a chat message)."""
	try:
		if log.channel == "Push":
			_deliver_push(log)
		elif log.channel == "WhatsApp":
			_deliver_whatsapp(log)
		log.status = "Sent"
		log.error = None
	except Exception as e:
		log.status = "Failed"
		log.attempts = (log.attempts or 0) + 1
		log.error = str(e)[:500]
	log.last_attempt_at = now_datetime()
	log.save(ignore_permissions=True)


def _get_vapid_config():
	config = frappe.get_single("Notification Config")
	if not config.vapid_public_key or not config.get_password("vapid_private_key", raise_exception=False):
		raise Exception("VAPID keys not configured (Notification Config).")
	return config


def _deliver_push(log):
	subscriptions = frappe.get_all(
		"Push Subscription", filters={"user": log.recipient}, fields=["endpoint", "p256dh", "auth"]
	)
	if not subscriptions:
		raise Exception("No Push Subscription registered for this user yet.")

	from pywebpush import webpush

	config = _get_vapid_config()
	context = frappe.parse_json(log.context) if log.context else {}
	payload = frappe.as_json({"template": log.template, "context": context})

	errors = []
	for sub in subscriptions:
		try:
			webpush(
				subscription_info={
					"endpoint": sub.endpoint,
					"keys": {"p256dh": sub.p256dh, "auth": sub.auth},
				},
				data=payload,
				vapid_private_key=config.get_password("vapid_private_key"),
				vapid_claims={"sub": f"mailto:{config.vapid_claims_email}"},
			)
		except Exception as e:
			errors.append(str(e))
	if errors and len(errors) == len(subscriptions):
		raise Exception("; ".join(errors))


def _deliver_whatsapp(log):
	import requests

	config = frappe.get_single("Notification Config")
	token = config.get_password("whatsapp_access_token", raise_exception=False)
	if not token or not config.whatsapp_phone_number_id:
		raise Exception("WhatsApp Cloud API not configured (Notification Config).")

	context = frappe.parse_json(log.context) if log.context else {}
	phone = context.get("phone")
	if not phone:
		raise Exception("No phone number in notification context.")

	response = requests.post(
		f"https://graph.facebook.com/v19.0/{config.whatsapp_phone_number_id}/messages",
		headers={"Authorization": f"Bearer {token}"},
		json={
			"messaging_product": "whatsapp",
			"to": phone,
			"type": "text",
			"text": {"body": context.get("message", log.template)},
		},
		timeout=10,
	)
	response.raise_for_status()


def register_push_subscription(user, endpoint, p256dh, auth):
	"""Records a browser's push subscription. Whitelisted wrapper lives in
	notification_api.py — this is the underlying logic, callable from tests without going
	through a whitelisted-function permission context."""
	existing = frappe.db.get_value("Push Subscription", {"user": user, "endpoint": endpoint}, "name")
	if not existing:
		frappe.get_doc(
			{
				"doctype": "Push Subscription",
				"user": user,
				"endpoint": endpoint,
				"p256dh": p256dh,
				"auth": auth,
			}
		).insert(ignore_permissions=True)
	retry_pending_notifications(user)


def retry_pending_notifications(user):
	"""Part E: "retried on next login and on new Push Subscription registration" — covers
	'notify even if offline, deliver once back online' uniformly."""
	pending = frappe.get_all("Comms Log", filters={"recipient": user, "status": ["in", ["Pending", "Failed"]]})
	for row in pending:
		attempt_push_delivery(frappe.get_doc("Comms Log", row.name))


def retry_pending_notifications_on_login(login_manager):
	"""hooks.py on_login — Frappe passes the LoginManager, whose .user is the logged-in user."""
	retry_pending_notifications(login_manager.user)
