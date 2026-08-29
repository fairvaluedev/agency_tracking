# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe

from agency_tracking.notification_engine import register_push_subscription as _register_push_subscription
from agency_tracking.watchdogs import send_wakala_reminder


@frappe.whitelist()
def subscribe_to_push(endpoint, p256dh, auth):
	"""A user subscribing their own browser — never on behalf of anyone else."""
	_register_push_subscription(frappe.session.user, endpoint, p256dh, auth)
	return {"status": "subscribed"}


@frappe.whitelist()
def trigger_wakala_reminder(clearance_step_name):
	"""business-workflow-srs.md: "plus staff can trigger a reminder manually any time" — the
	escape hatch alongside the automatic Fri/Sat/Sun watchdog."""
	step = frappe.get_doc("Clearance Step", clearance_step_name)
	if step.step_type != "Embassy":
		frappe.throw("This is only meaningful for an Embassy clearance step.", frappe.ValidationError)
	if not step.has_permission("read"):
		frappe.throw("Not permitted.", frappe.PermissionError)
	send_wakala_reminder(clearance_step_name, step.placement)
	return {"status": "reminder sent"}


@frappe.whitelist(allow_guest=False)
def get_push_subscription_status():
	"""Read-only -- tells the frontend whether the current user already has an active Push
	Subscription, so it knows whether to show the manual \"enable notifications\" fallback
	button (needed when the browser's own permission prompt is auto-dismissed or the user
	cancels it without realizing)."""
	return {
		"subscribed": bool(
			frappe.db.exists("Push Subscription", {"user": frappe.session.user})
		)
	}
