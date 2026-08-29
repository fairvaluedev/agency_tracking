# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.tests.test_clearance_engine import saudi_selected_placement
from agency_tracking.clearance_engine import assign_clearance_step
from agency_tracking.state_machine import transition
from agency_tracking.watchdogs import contract_age_watchdog, medical_expiry_watchdog, wakala_reminder_watchdog


def placement_with_lmis_officer(tag):
	placement = saudi_selected_placement(tag)
	transition(placement, "Processing")
	lmis_step = frappe.db.get_value(
		"Clearance Step", {"placement": placement.name, "step_type": "LMIS Clearance"}, "name"
	)
	officer = frappe.get_doc(
		{
			"doctype": "User",
			"email": f"wd-{tag}@example.com",
			"first_name": f"WD {tag}",
			"send_welcome_email": 0,
			"roles": [{"role": "Clearance Officer"}],
		}
	).insert(ignore_permissions=True)
	assign_clearance_step(lmis_step, officer.name)
	return placement, officer


def contractor_user_for(placement):
	"""2026-08-29: Wakala reminders go to the paying Contractor's user, not the LMIS officer
	(the previous, wrong recipient) -- see watchdogs.send_wakala_reminder."""
	contractor_name = frappe.db.get_value("Placement", placement.name, "contractor")
	return frappe.db.get_value("Contractor", contractor_name, "user")


class TestWatchdogs(FrappeTestCase):
	def test_medical_expiry_notifies_at_each_tier(self):
		placement, officer = placement_with_lmis_officer("wd01")
		frappe.db.set_value(
			"Applicant", placement.applicant, "medical_expiry_date", frappe.utils.add_days(frappe.utils.today(), 7)
		)
		medical_expiry_watchdog()
		self.assertTrue(
			frappe.db.exists("Comms Log", {"recipient": officer.name, "template": "medical_expiry_warning"})
		)

	def test_medical_expiry_ignores_non_tier_dates(self):
		placement, officer = placement_with_lmis_officer("wd02")
		frappe.db.set_value(
			"Applicant", placement.applicant, "medical_expiry_date", frappe.utils.add_days(frappe.utils.today(), 8)
		)
		medical_expiry_watchdog()
		self.assertFalse(
			frappe.db.exists("Comms Log", {"recipient": officer.name, "template": "medical_expiry_warning"})
		)

	def test_medical_expiry_skips_applicants_without_active_placement(self):
		applicant = frappe.get_doc(
			{
				"doctype": "Applicant",
				"entry_track": "Standard",
				"full_name": "Watchdog Unassigned",
				"gender": "Female",
				"nationality": "Ethiopia",
				"phone": "+251900000000",
				"address": "Addis Ababa",
				"medical_expiry_date": frappe.utils.add_days(frappe.utils.today(), 7),
			}
		).insert(ignore_permissions=True)
		# Should not raise even though there's no active_placement / recipient to notify.
		medical_expiry_watchdog()
		self.assertFalse(frappe.db.exists("Comms Log", {"template": "medical_expiry_warning", "context": ["like", f"%{applicant.name}%"]}))

	def test_contract_age_alerts_past_threshold(self):
		placement, officer = placement_with_lmis_officer("wd03")
		config = frappe.get_single("Notification Config")
		config.contract_age_threshold_days = 30
		config.save(ignore_permissions=True)
		frappe.db.set_value(
			"Placement", placement.name, "contract_signed_date", frappe.utils.add_days(frappe.utils.today(), -45)
		)
		contract_age_watchdog()
		self.assertTrue(frappe.db.exists("Comms Log", {"recipient": officer.name, "template": "contract_age_alert"}))

	def test_contract_age_does_not_alert_within_threshold(self):
		placement, officer = placement_with_lmis_officer("wd04")
		config = frappe.get_single("Notification Config")
		config.contract_age_threshold_days = 30
		config.save(ignore_permissions=True)
		frappe.db.set_value(
			"Placement", placement.name, "contract_signed_date", frappe.utils.add_days(frappe.utils.today(), -5)
		)
		contract_age_watchdog()
		self.assertFalse(frappe.db.exists("Comms Log", {"recipient": officer.name, "template": "contract_age_alert"}))

	def test_contract_age_does_not_alert_departed_placements(self):
		from agency_tracking.agency_tracking.tests.test_finance_engine import departed_placement

		placement = departed_placement("wd05")
		frappe.db.set_value(
			"Placement", placement.name, "contract_signed_date", frappe.utils.add_days(frappe.utils.today(), -365)
		)
		contract_age_watchdog()
		self.assertFalse(
			frappe.db.exists("Comms Log", {"template": "contract_age_alert", "context": ["like", f"%{placement.name}%"]})
		)

	def test_wakala_reminder_sent_for_unpaid_step(self):
		# The Saudi corridor already auto-creates an Embassy Clearance Step when the placement
		# enters Processing (Step 7) — Pending by default, which already satisfies the
		# watchdog's "unpaid" filter. No need to (and must not) create a second one for the
		# same placement, or the watchdog correctly finds two and this assertion would wrongly
		# look like a bug in the watchdog rather than the fixture.
		placement, officer = placement_with_lmis_officer("wd06")
		recipient = contractor_user_for(placement)

		wakala_reminder_watchdog()

		push_count = frappe.db.count(
			"Comms Log", filters={"recipient": recipient, "template": "wakala_payment_reminder", "channel": "Push"}
		)
		whatsapp_count = frappe.db.count(
			"Comms Log",
			filters={"recipient": recipient, "template": "wakala_payment_reminder", "channel": "WhatsApp"},
		)
		self.assertEqual(push_count, 1)
		self.assertEqual(whatsapp_count, 1)

	def test_wakala_reminder_skipped_once_paid(self):
		placement, officer = placement_with_lmis_officer("wd07")
		recipient = contractor_user_for(placement)
		frappe.db.set_value(
			"Clearance Step",
			{"placement": placement.name, "step_type": "Embassy"},
			{"status": "Stamped", "wakala_status": "Paid"},
		)

		wakala_reminder_watchdog()

		self.assertFalse(
			frappe.db.exists("Comms Log", {"recipient": recipient, "template": "wakala_payment_reminder"})
		)
