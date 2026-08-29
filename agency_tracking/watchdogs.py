# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part E: "Watchdogs sharing this pipeline: medical expiry (14/10/7/3/1-day tiers), contract-age
# threshold (admin-configurable), Wakala payment reminders (twice-weekly + manual trigger)."
# Wired into hooks.py's scheduler — daily for medical/contract-age, a cron entry for Wakala's
# "twice a week" cadence.

import frappe
from frappe.utils import add_days, getdate, today

from agency_tracking.clearance_engine import get_lmis_officer
from agency_tracking.notification_engine import notify

MEDICAL_EXPIRY_TIERS_DAYS = [14, 10, 7, 3, 1]


def _recipient_for_placement(placement_name):
	"""No single "owner" field exists on Placement — the natural recipient is whoever's
	currently doing the LMIS-family step (falls back to nobody, silently, if unassigned; a
	watchdog isn't the place to invent a recipient that doesn't reflect real assignment)."""
	placement = frappe.get_doc("Placement", placement_name)
	return get_lmis_officer(placement)


def medical_expiry_watchdog():
	"""Applicant.medical_expiry_date within one of the 14/10/7/3/1-day tiers. Only meaningful
	for applicants who've actually been selected (active_placement set) — before that there's
	no assigned officer to notify."""
	for tier_days in MEDICAL_EXPIRY_TIERS_DAYS:
		target_date = add_days(today(), tier_days)
		applicants = frappe.get_all(
			"Applicant",
			filters={"medical_expiry_date": target_date, "active_placement": ["is", "set"]},
			fields=["name", "active_placement", "full_name"],
		)
		for applicant in applicants:
			recipient = _recipient_for_placement(applicant.active_placement)
			if recipient:
				notify(
					recipient,
					"medical_expiry_warning",
					{
						"applicant": applicant.name,
						"full_name": applicant.full_name,
						"days_remaining": tier_days,
						"placement": applicant.active_placement,
					},
				)


def contract_age_watchdog():
	"""Part A.4: contract-age clock from Placement.contract_signed_date, admin-configurable
	threshold, alerts only while still active (not yet Departed)."""
	threshold_days = frappe.get_single("Notification Config").contract_age_threshold_days or 30
	cutoff_date = add_days(today(), -threshold_days)

	placements = frappe.get_all(
		"Placement",
		filters={
			"status": ["!=", "Departed"],
			"contract_signed_date": ["<=", cutoff_date],
		},
		fields=["name", "contract_signed_date"],
	)
	for placement in placements:
		recipient = _recipient_for_placement(placement.name)
		if recipient:
			age_days = (getdate(today()) - getdate(placement.contract_signed_date)).days
			notify(
				recipient,
				"contract_age_alert",
				{"placement": placement.name, "age_days": age_days, "threshold_days": threshold_days},
			)


def wakala_reminder_watchdog():
	"""2026-08-29 fix: the Wakala fee is paid by the *foreign agency* (Contractor), not internal
	staff — this watchdog previously (wrongly) notified the LMIS officer instead. Also moved
	from Mon/Thu to Fri/Sat/Sun (business ask: remind before the Monday document-submission
	deadline, not after). Wakala now lives as fields on the "Embassy" step (was a standalone
	"Embassy/Wakala" step_type) — see clearance_step.json's wakala_status field."""
	unpaid_steps = frappe.get_all(
		"Clearance Step",
		filters={"step_type": "Embassy", "wakala_status": ["!=", "Paid"], "status": ["not in", ["Stamped", "Cancelled"]]},
		fields=["name", "placement"],
	)
	for step in unpaid_steps:
		send_wakala_reminder(step.name, step.placement)


def send_wakala_reminder(clearance_step_name, placement_name):
	"""Recipient is the paying Contractor's linked User — never internal staff (that was the
	bug). WhatsApp delivery needs a `phone` key in context (pulled from the Contractor's User's
	mobile_no); previously nothing supplied one, so WhatsApp silently failed every time."""
	contractor_name = frappe.db.get_value("Placement", placement_name, "contractor")
	if not contractor_name:
		return
	recipient = frappe.db.get_value("Contractor", contractor_name, "user")
	if not recipient:
		return
	phone = frappe.db.get_value("User", recipient, "mobile_no")
	notify(
		recipient,
		"wakala_payment_reminder",
		{"clearance_step": clearance_step_name, "placement": placement_name},
	)
	# WhatsApp reminder too, per the spec's explicit "WhatsApp + portal notification" pairing —
	# whatsapp delivery falls back gracefully (attempt_push_delivery never raises) if the
	# contractor's phone isn't set or WhatsApp isn't configured yet.
	notify(
		recipient,
		"wakala_payment_reminder",
		{
			"clearance_step": clearance_step_name,
			"placement": placement_name,
			"phone": phone,
			"message": f"Wakala payment reminder for Clearance Step {clearance_step_name}.",
		},
		channel="WhatsApp",
	)


TAESHIR_INJAZ_REMINDER_TIERS_DAYS = [3, 2, 1]


def taeshir_injaz_reminder_watchdog():
	"""New (2026-08-29): reminds whoever holds the Saudi Taeshir role when a Taeshir
	appointment is 3/2/1 days out and Injaz still hasn't been paid — arriving at the
	appointment unpaid forfeits the (separate) appointment fee. Push only, deliberately no
	WhatsApp (that channel is reserved for reaching the external foreign agency via Wakala;
	Taeshir/Injaz reminders go to internal staff already using the system)."""
	for tier_days in TAESHIR_INJAZ_REMINDER_TIERS_DAYS:
		target_date = add_days(today(), tier_days)
		due_steps = frappe.get_all(
			"Clearance Step",
			filters={
				"step_type": "Taeshir",
				"appointment_date": target_date,
				"injaz_payment_status": ["!=", "Paid"],
				"status": ["not in", ["Issued", "Complete", "Cancelled"]],
			},
			fields=["name", "placement"],
		)
		for step in due_steps:
			for recipient in frappe.get_all(
				"Has Role", filters={"role": "Saudi Taeshir"}, pluck="parent"
			):
				notify(
					recipient,
					"taeshir_injaz_payment_reminder",
					{
						"clearance_step": step.name,
						"placement": step.placement,
						"days_remaining": tier_days,
					},
				)
