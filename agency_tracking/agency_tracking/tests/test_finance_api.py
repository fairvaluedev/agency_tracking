# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.tests.test_clearance_engine import saudi_selected_placement
from agency_tracking.finance_api import (
	approve_transaction,
	create_commission_batch,
	get_fx_rate,
	log_stage_expense,
	log_stage_income,
	reject_transaction,
	set_fx_rate,
	settle_batch,
	trigger_early_commission_accrual,
	void_transaction,
)
from agency_tracking.finance_engine import record_fx_rate


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

	def test_any_internal_staff_can_log_expense(self):
		# 2026-08-29: logging is open to any internal staff role, not just whoever's assigned
		# to a placement's current stage -- Finance approval is the real gate now.
		placement = saudi_selected_placement("fa01")
		officer = make_role_user("fa01", "Clearance Officer")
		record_fx_rate("USD", 55.0, frappe.utils.today())

		frappe.set_user(officer.name)
		result = log_stage_expense(50, "USD", "Biometric appointment fee", placement=placement.name)
		self.assertEqual(result["transaction_type"], "Expense")
		self.assertEqual(result["status"], "Pending")
		self.assertEqual(result["amount_birr"], 50 * 55.0)

	def test_general_expense_without_placement_is_loggable(self):
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		manager = make_role_user("fa02", "Manager")
		frappe.set_user(manager.name)
		result = log_stage_expense(75, "ETB", "Office rent share")
		self.assertEqual(result["transaction_type"], "Expense")
		self.assertFalse(result["placement"])

	def test_non_internal_role_cannot_log(self):
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		agency_user = make_role_user("fa02b", "Foreign Agency")
		frappe.set_user(agency_user.name)
		with self.assertRaises(frappe.PermissionError):
			log_stage_expense(10, "ETB", "Should be blocked")

	def test_manager_can_always_log_income(self):
		placement = saudi_selected_placement("fa03")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		manager = make_role_user("fa03", "Manager")

		frappe.set_user(manager.name)
		result = log_stage_income(200, "ETB", "Walk-in registration fee", placement=placement.name)
		self.assertEqual(result["transaction_type"], "Income")

	def test_non_finance_role_sees_only_own_rows(self):
		# 2026-08-29: no longer a hard "1=0" for everyone but Finance Manager/Admin -- staff
		# can see their own logged rows, just not everyone else's.
		placement = saudi_selected_placement("fa04")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		manager = make_role_user("fa04", "Manager")
		frappe.set_user(manager.name)
		log_stage_income(100, "ETB", "test", placement=placement.name)

		frappe.set_user("Administrator")
		officer = make_role_user("fa04b", "Clearance Officer")
		frappe.set_user(officer.name)
		self.assertEqual(len(frappe.get_list("Applicant Transaction")), 0)

		own = log_stage_income(50, "ETB", "own entry", placement=placement.name)
		visible = frappe.get_list("Applicant Transaction")
		self.assertEqual([v.name for v in visible], [own["name"]])

	def test_finance_manager_can_list_transactions(self):
		placement = saudi_selected_placement("fa05")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		frappe.set_user("Administrator")
		log_stage_income(100, "ETB", "test", placement=placement.name)

		finance_manager = make_role_user("fa05", "Finance Manager")
		frappe.set_user(finance_manager.name)
		visible = frappe.get_list("Applicant Transaction")
		self.assertGreaterEqual(len(visible), 1)

	def test_approve_transaction_requires_finance_role(self):
		placement = saudi_selected_placement("fa06")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		result = log_stage_income(100, "ETB", "test", placement=placement.name)

		officer = make_role_user("fa06", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			approve_transaction(result["name"])

	def test_approve_transaction_succeeds(self):
		placement = saudi_selected_placement("fa06b")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		result = log_stage_income(100, "ETB", "test", placement=placement.name)

		approved = approve_transaction(result["name"])
		self.assertEqual(approved["status"], "Approved")
		self.assertEqual(approved["approved_by"], "Administrator")

	def test_reject_transaction_requires_reason(self):
		placement = saudi_selected_placement("fa06c")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		result = log_stage_income(100, "ETB", "test", placement=placement.name)

		with self.assertRaises(frappe.ValidationError):
			reject_transaction(result["name"], "")

	def test_reject_transaction_succeeds(self):
		placement = saudi_selected_placement("fa06d")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		result = log_stage_income(100, "ETB", "test", placement=placement.name)

		rejected = reject_transaction(result["name"], "Duplicate entry")
		self.assertEqual(rejected["status"], "Rejected")
		self.assertEqual(rejected["rejection_reason"], "Duplicate entry")

	def test_void_transaction_requires_reason(self):
		placement = saudi_selected_placement("fa07")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		result = log_stage_income(100, "ETB", "test", placement=placement.name)
		approve_transaction(result["name"])

		with self.assertRaises(frappe.ValidationError):
			void_transaction(result["name"], "")

	def test_void_transaction_requires_finance_role(self):
		placement = saudi_selected_placement("fa08")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		result = log_stage_income(100, "ETB", "test", placement=placement.name)
		approve_transaction(result["name"])

		officer = make_role_user("fa08", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			void_transaction(result["name"], "Entered in error")

	def test_void_transaction_only_from_approved(self):
		placement = saudi_selected_placement("fa08b")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		result = log_stage_income(100, "ETB", "test", placement=placement.name)
		with self.assertRaises(frappe.ValidationError):
			void_transaction(result["name"], "Entered in error")

	def test_void_transaction_succeeds_and_stays_visible(self):
		placement = saudi_selected_placement("fa09")
		record_fx_rate("ETB", 1.0, frappe.utils.today())
		result = log_stage_income(100, "ETB", "test", placement=placement.name)
		approve_transaction(result["name"])

		voided = void_transaction(result["name"], "Duplicate entry")
		self.assertEqual(voided["status"], "Voided")
		self.assertTrue(frappe.db.exists("Applicant Transaction", result["name"]))
		self.assertTrue(
			frappe.db.exists(
				"Process Event",
				{"reference_doctype": "Applicant Transaction", "reference_name": result["name"], "event_type": "Transition", "to_status": "Voided"},
			)
		)

	def test_early_accrual_trigger_is_idempotent(self):
		placement = saudi_selected_placement("fa10")
		frappe.db.set_value(
			"Placement", placement.name, {"manual_commission_amount": 300, "manual_commission_currency": "USD"}
		)
		record_fx_rate("USD", 55.0, frappe.utils.today())

		result = trigger_early_commission_accrual(placement.name)
		self.assertEqual(result["transaction_type"], "Commission")
		self.assertEqual(result["status"], "Approved")
		with self.assertRaises(frappe.ValidationError):
			trigger_early_commission_accrual(placement.name)

	def test_early_accrual_requires_finance_or_manager_role(self):
		placement = saudi_selected_placement("fa11")
		frappe.db.set_value(
			"Placement", placement.name, {"manual_commission_amount": 300, "manual_commission_currency": "USD"}
		)
		record_fx_rate("USD", 55.0, frappe.utils.today())

		officer = make_role_user("fa11", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			trigger_early_commission_accrual(placement.name)

	def test_fx_rate_endpoints_require_finance_role(self):
		officer = make_role_user("fa12", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			get_fx_rate("USD")
		with self.assertRaises(frappe.PermissionError):
			set_fx_rate("USD", 55.0)

	def test_batch_and_settle_require_finance_role(self):
		placement = saudi_selected_placement("fa13")
		record_fx_rate("USD", 55.0, frappe.utils.today())
		frappe.db.set_value(
			"Placement", placement.name, {"manual_commission_amount": 300, "manual_commission_currency": "USD"}
		)
		trigger_early_commission_accrual(placement.name)

		officer = make_role_user("fa13", "Clearance Officer")
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
