# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.tests.test_clearance_engine import saudi_selected_placement
from agency_tracking.clearance_engine import assign_clearance_step
from agency_tracking.finance_api import (
	create_commission_batch,
	get_fx_rate,
	log_stage_expense,
	log_stage_income,
	set_fx_rate,
	settle_batch,
	trigger_early_commission_accrual,
	void_transaction,
)
from agency_tracking.finance_engine import record_fx_rate
from agency_tracking.state_machine import transition


def make_role_user(tag, role):
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": f"fa-{tag}@example.com",
			"first_name": f"FA {tag}",
			"send_welcome_email": 0,
			"roles": [{"role": role}],
		}
	).insert(ignore_permissions=True)


class TestFinanceAPI(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_assigned_officer_can_log_expense(self):
		placement = saudi_selected_placement("fa01")
		transition(placement, "Processing")
		step_name = frappe.get_all("Clearance Step", filters={"placement": placement.name}, limit=1, pluck="name")[0]
		officer = make_role_user("fa01", "Clearance Officer")
		assign_clearance_step(step_name, officer.name)
		record_fx_rate("USD", 55.0, frappe.utils.today())

		frappe.set_user(officer.name)
		result = log_stage_expense(placement.name, 50, "USD", "Biometric appointment fee")
		self.assertEqual(result["transaction_type"], "Expense")
		self.assertEqual(result["amount_birr"], 50 * 55.0)

	def test_unassigned_officer_cannot_log_expense(self):
		placement = saudi_selected_placement("fa02")
		transition(placement, "Processing")
		bystander = make_role_user("fa02", "Clearance Officer")
		record_fx_rate("USD", 55.0, frappe.utils.today())

		frappe.set_user(bystander.name)
		with self.assertRaises(frappe.PermissionError):
			log_stage_expense(placement.name, 50, "USD", "Should be blocked")

	def test_manager_can_always_log_income(self):
		placement = saudi_selected_placement("fa03")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		manager = make_role_user("fa03", "Manager")

		frappe.set_user(manager.name)
		result = log_stage_income(placement.name, 200, "ETB", "Walk-in registration fee")
		self.assertEqual(result["transaction_type"], "Income")

	def test_non_finance_role_cannot_list_transactions(self):
		placement = saudi_selected_placement("fa04")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		manager = make_role_user("fa04", "Manager")
		frappe.set_user(manager.name)
		log_stage_income(placement.name, 100, "ETB", "test")

		frappe.set_user("Administrator")
		officer = make_role_user("fa04b", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list("Applicant Transaction")

	def test_finance_manager_can_list_transactions(self):
		placement = saudi_selected_placement("fa05")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		frappe.set_user("Administrator")
		log_stage_income(placement.name, 100, "ETB", "test")

		finance_manager = make_role_user("fa05", "Finance Manager")
		frappe.set_user(finance_manager.name)
		visible = frappe.get_list("Applicant Transaction")
		self.assertGreaterEqual(len(visible), 1)

	def test_void_transaction_requires_reason(self):
		placement = saudi_selected_placement("fa06")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		result = log_stage_income(placement.name, 100, "ETB", "test")

		with self.assertRaises(frappe.ValidationError):
			void_transaction(result["name"], "")

	def test_void_transaction_requires_finance_role(self):
		placement = saudi_selected_placement("fa07")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		result = log_stage_income(placement.name, 100, "ETB", "test")

		officer = make_role_user("fa07", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			void_transaction(result["name"], "Entered in error")

	def test_void_transaction_succeeds_and_stays_visible(self):
		placement = saudi_selected_placement("fa08")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		result = log_stage_income(placement.name, 100, "ETB", "test")

		voided = void_transaction(result["name"], "Duplicate entry")
		self.assertEqual(voided["status"], "Voided")
		self.assertTrue(frappe.db.exists("Applicant Transaction", result["name"]))
		self.assertTrue(
			frappe.db.exists(
				"Process Event",
				{"reference_doctype": "Applicant Transaction", "reference_name": result["name"], "event_type": "Voided"},
			)
		)

	def test_early_accrual_trigger_is_idempotent(self):
		placement = saudi_selected_placement("fa09")
		frappe.db.set_value(
			"Placement", placement.name, {"manual_commission_amount": 300, "manual_commission_currency": "USD"}
		)
		record_fx_rate("USD", 55.0, frappe.utils.today())

		result = trigger_early_commission_accrual(placement.name)
		self.assertEqual(result["transaction_type"], "Commission")
		with self.assertRaises(frappe.ValidationError):
			trigger_early_commission_accrual(placement.name)

	def test_early_accrual_requires_finance_or_manager_role(self):
		placement = saudi_selected_placement("fa10")
		frappe.db.set_value(
			"Placement", placement.name, {"manual_commission_amount": 300, "manual_commission_currency": "USD"}
		)
		record_fx_rate("USD", 55.0, frappe.utils.today())

		officer = make_role_user("fa10", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			trigger_early_commission_accrual(placement.name)

	def test_fx_rate_endpoints_require_finance_role(self):
		officer = make_role_user("fa11", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			get_fx_rate("USD")
		with self.assertRaises(frappe.PermissionError):
			set_fx_rate("USD", 55.0)

	def test_batch_and_settle_require_finance_role(self):
		placement = saudi_selected_placement("fa12")
		record_fx_rate("USD", 55.0, frappe.utils.today())
		frappe.db.set_value(
			"Placement", placement.name, {"manual_commission_amount": 300, "manual_commission_currency": "USD"}
		)
		trigger_early_commission_accrual(placement.name)

		officer = make_role_user("fa12", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			create_commission_batch(placement.contractor, "Saudi Arabia")

		frappe.set_user("Administrator")
		batch = create_commission_batch(placement.contractor, "Saudi Arabia")

		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			settle_batch(batch["name"], "BANK-REF-1")

		frappe.set_user("Administrator")
		settled = settle_batch(batch["name"], "BANK-REF-1")
		self.assertEqual(settled["status"], "Settled")
