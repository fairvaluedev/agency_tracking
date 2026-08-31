# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.doctype.placement.test_placement import make_contractor
from agency_tracking.agency_tracking.tests.test_clearance_engine import saudi_selected_placement
from agency_tracking.agency_tracking.tests.test_state_machine import complete_all_clearance_steps
from agency_tracking.clearance_api import complete_clearance_step
from agency_tracking.finance_engine import (
	accrue_commission,
	create_batch_request,
	get_commission_rate,
	get_fx_rate,
	is_assigned_to_placement,
	record_fx_rate,
)
from agency_tracking.state_machine import transition


def departed_placement(tag, amount=250):
	# amount is parameterized (not a shared constant) so tests that need a unique
	# total_amount_birr to disambiguate matching logic (reconciliation tests) don't collide
	# with other tests' leftover unsettled batches sitting around from earlier in the same
	# run at the same default amount*rate.
	placement = saudi_selected_placement(tag)
	# Accrual on reaching Departed is now best-effort (state_machine.transition() logs and
	# swallows side-effect failures rather than corrupting the transition itself) — set the
	# commission data up front so accrual actually succeeds for tests that need a real
	# transaction to batch against.
	frappe.db.set_value(
		"Placement", placement.name, {"manual_commission_amount": amount, "manual_commission_currency": "USD"}
	)
	placement.reload()
	transition(placement, "Processing")
	complete_all_clearance_steps(placement.name)
	transition(placement, "Stamped")
	frappe.db.set_value("Placement", placement.name, "ticket_number", f"TK-{tag}")
	placement.reload()
	transition(placement, "Ticketed")
	frappe.db.set_value("Placement", placement.name, "medical_2_status", "FIT")
	placement.reload()
	transition(placement, "Departed")
	placement.reload()
	return placement


class TestFinanceEngine(FrappeTestCase):
	def test_record_and_get_exact_fx_rate(self):
		record_fx_rate("USD", 55.5, "2026-08-20")
		rate, rate_date = get_fx_rate("USD", "2026-08-20")
		self.assertEqual(rate, 55.5)
		self.assertEqual(str(rate_date), "2026-08-20")

	def test_get_fx_rate_falls_back_to_most_recent_earlier_rate(self):
		record_fx_rate("SAR", 14.8, "2026-08-01")
		rate, rate_date = get_fx_rate("SAR", "2026-08-15")
		self.assertEqual(rate, 14.8)
		self.assertEqual(str(rate_date), "2026-08-01")

	def test_get_fx_rate_throws_when_nothing_recorded(self):
		with self.assertRaises(frappe.ValidationError):
			get_fx_rate("QAR", "2020-01-01")

	def test_record_fx_rate_updates_existing_same_day_rate(self):
		record_fx_rate("KWD", 180.0, "2026-08-22")
		record_fx_rate("KWD", 182.5, "2026-08-22")
		rate, _ = get_fx_rate("KWD", "2026-08-22")
		self.assertEqual(rate, 182.5)

	def test_muayena_requires_manual_amount(self):
		placement = saudi_selected_placement("fe01")
		with self.assertRaises(frappe.ValidationError):
			get_commission_rate(placement)

	def test_muayena_uses_manual_amount_and_currency(self):
		placement = saudi_selected_placement("fe02")
		frappe.db.set_value(
			"Placement", placement.name, {"manual_commission_amount": 500, "manual_commission_currency": "USD"}
		)
		placement.reload()
		amount, currency = get_commission_rate(placement)
		self.assertEqual(amount, 500)
		self.assertEqual(currency, "USD")

	def test_standard_track_uses_contractor_default_rate(self):
		contractor = make_contractor("fe03", country="Saudi Arabia")
		contractor.append("default_commission_rates", {"destination_country": "Saudi Arabia", "rate": 300, "currency": "USD"})
		contractor.save(ignore_permissions=True)

		from agency_tracking.agency_tracking.doctype.placement.test_placement import registered_applicant

		applicant = registered_applicant(
			"fe03", entry_track="Standard", destination_country="Saudi Arabia"
		)
		from agency_tracking.cv_api import generate_cv
		from agency_tracking.portal_api import select_candidate

		generate_cv(applicant.name)
		frappe.set_user(contractor.user)
		result = select_candidate(applicant.name)
		frappe.set_user("Administrator")
		placement = frappe.get_doc("Placement", result["name"])

		amount, currency = get_commission_rate(placement)
		self.assertEqual(amount, 300)
		self.assertEqual(currency, "USD")

	def test_standard_track_throws_when_no_default_rate_configured(self):
		placement = saudi_selected_placement("fe04")
		# force Standard-like resolution path directly against a Muayena fixture's contractor,
		# which has no default_commission_rates configured
		applicant = frappe.get_doc("Applicant", placement.applicant)
		applicant.db_set("entry_track", "Standard")
		with self.assertRaises(frappe.ValidationError):
			get_commission_rate(placement)

	def test_accrual_creates_commission_transaction(self):
		record_fx_rate("USD", 55.0, frappe.utils.today())
		placement = saudi_selected_placement("fe05")
		frappe.db.set_value(
			"Placement", placement.name, {"manual_commission_amount": 400, "manual_commission_currency": "USD"}
		)
		placement.reload()
		txn = accrue_commission(placement)
		self.assertIsNotNone(txn)
		self.assertEqual(txn.transaction_type, "Commission")
		self.assertEqual(txn.amount_birr, 400 * 55.0)

	def test_accrual_is_idempotent(self):
		record_fx_rate("USD", 55.0, frappe.utils.today())
		placement = saudi_selected_placement("fe06")
		frappe.db.set_value(
			"Placement", placement.name, {"manual_commission_amount": 400, "manual_commission_currency": "USD"}
		)
		placement.reload()
		first = accrue_commission(placement)
		second = accrue_commission(placement)
		self.assertIsNotNone(first)
		self.assertIsNone(second)
		count = frappe.db.count(
			"Applicant Transaction", filters={"placement": placement.name, "transaction_type": "Commission"}
		)
		self.assertEqual(count, 1)

	def test_full_lifecycle_accrues_commission_on_departed(self):
		record_fx_rate("USD", 55.0, frappe.utils.today())
		placement = saudi_selected_placement("fe07")
		frappe.db.set_value(
			"Placement", placement.name, {"manual_commission_amount": 350, "manual_commission_currency": "USD"}
		)
		placement.reload()

		transition(placement, "Processing")
		complete_all_clearance_steps(placement.name)
		transition(placement, "Stamped")
		frappe.db.set_value("Placement", placement.name, "ticket_number", "TK-fe07")
		placement.reload()
		transition(placement, "Ticketed")
		frappe.db.set_value("Placement", placement.name, "medical_2_status", "FIT")
		placement.reload()
		transition(placement, "Departed")

		self.assertTrue(
			frappe.db.exists(
				"Applicant Transaction",
				{"placement": placement.name, "transaction_type": "Commission", "status": "Approved"},
			)
		)

	def test_is_assigned_to_placement_via_clearance_step_todo(self):
		placement = saudi_selected_placement("fe08")
		transition(placement, "Processing")
		step_name = frappe.get_all("Clearance Step", filters={"placement": placement.name}, limit=1, pluck="name")[0]

		officer = frappe.get_doc(
			{
				"doctype": "User",
				"email": "fe-officer@example.com",
				"first_name": "FE Officer",
				"send_welcome_email": 0,
				"roles": [{"role": "Clearance Officer"}],
			}
		).insert(ignore_permissions=True)
		from agency_tracking.clearance_engine import assign_clearance_step

		assign_clearance_step(step_name, officer.name)
		self.assertTrue(is_assigned_to_placement(officer.name, placement.name))
		self.assertFalse(is_assigned_to_placement("Administrator", placement.name))

	def test_manual_batch_request_creation(self):
		record_fx_rate("USD", 55.0, frappe.utils.today())
		placement = departed_placement("fe09")
		contractor_name = placement.contractor

		batch = create_batch_request(contractor_name, "Saudi Arabia")
		self.assertEqual(batch.status, "Draft")
		self.assertEqual(len(batch.items), 1)
		self.assertGreater(batch.total_amount_birr, 0)

	def test_batch_request_marks_transactions_as_batched(self):
		record_fx_rate("USD", 55.0, frappe.utils.today())
		placement = departed_placement("fe10")
		contractor_name = placement.contractor

		batch = create_batch_request(contractor_name, "Saudi Arabia")
		txn_name = batch.items[0].transaction
		self.assertEqual(frappe.db.get_value("Applicant Transaction", txn_name, "commission_batch_request"), batch.name)

	def test_no_owed_commissions_throws(self):
		contractor = make_contractor("fe11", country="Saudi Arabia")
		with self.assertRaises(frappe.ValidationError):
			create_batch_request(contractor.name, "Saudi Arabia")

	def test_auto_threshold_batching_triggers_at_threshold(self):
		record_fx_rate("USD", 55.0, frappe.utils.today())
		contractor = make_contractor("fe12", country="Saudi Arabia")
		contractor.batch_mode = "Auto-Threshold"
		contractor.batch_threshold = 2
		contractor.save(ignore_permissions=True)

		from agency_tracking.agency_tracking.doctype.placement.test_placement import registered_applicant

		def new_departed_placement_for_contractor(sub_tag):
			applicant = registered_applicant(
				sub_tag, entry_track="Muayena", destination_country="Saudi Arabia"
			)
			placement = frappe.get_doc(
				{
					"doctype": "Placement",
					"applicant": applicant.name,
					"contractor": contractor.name,
					"destination_country": "Saudi Arabia",
					"status": "Selected",
					"medical_selected_status": "FIT",
					"manual_commission_amount": 100,
					"manual_commission_currency": "USD",
				}
			).insert(ignore_permissions=True)
			frappe.db.set_value("Applicant", applicant.name, "active_placement", placement.name)
			transition(placement, "Processing")
			complete_all_clearance_steps(placement.name)
			transition(placement, "Stamped")
			frappe.db.set_value("Placement", placement.name, "ticket_number", f"TK-{sub_tag}")
			placement.reload()
			transition(placement, "Ticketed")
			frappe.db.set_value("Placement", placement.name, "medical_2_status", "FIT")
			placement.reload()
			transition(placement, "Departed")
			return placement

		new_departed_placement_for_contractor("fe12a")
		new_departed_placement_for_contractor("fe12b")

		self.assertTrue(frappe.db.exists("Commission Batch Request", {"contractor": contractor.name}))
