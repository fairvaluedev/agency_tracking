# Copyright (c) 2026, Agency and contributors
# See license.txt

import os

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.agency_tracking.tests.test_clearance_engine import saudi_selected_placement
from agency_tracking.finance_api import (
	approve_transaction,
	create_commission_batch,
	get_batch_invoice_pdf,
	get_fx_rate,
	log_stage_expense,
	log_stage_income,
	reject_transaction,
	set_fx_rate,
	settle_batch,
	settle_batch_items,
	trigger_early_commission_accrual,
	upload_batch_payment_proof,
	void_transaction,
)
from agency_tracking.finance_engine import record_fx_rate


def write_names_csv(filename, names):
	site_path = frappe.get_site_path("public", "files")
	os.makedirs(site_path, exist_ok=True)
	path = os.path.join(site_path, filename)
	with open(path, "w", newline="", encoding="utf-8") as f:
		for name in names:
			f.write(f"{name}\n")
	return f"/files/{filename}"


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
		manager = make_role_user("fa02", "Manager")
		frappe.set_user(manager.name)
		result = log_stage_expense(75, "ETB", "Office rent share")
		self.assertEqual(result["transaction_type"], "Expense")
		self.assertFalse(result["placement"])

	def test_non_internal_role_cannot_log(self):
		agency_user = make_role_user("fa02b", "Foreign Agency")
		frappe.set_user(agency_user.name)
		with self.assertRaises(frappe.PermissionError):
			log_stage_expense(10, "ETB", "Should be blocked")

	def test_manager_can_always_log_income(self):
		placement = saudi_selected_placement("fa03")
		manager = make_role_user("fa03", "Manager")

		frappe.set_user(manager.name)
		result = log_stage_income(200, "ETB", "Walk-in registration fee", placement=placement.name)
		self.assertEqual(result["transaction_type"], "Income")

	def test_non_finance_role_sees_only_own_rows(self):
		# 2026-08-29: no longer a hard "1=0" for everyone but Finance Manager/Admin -- staff
		# can see their own logged rows, just not everyone else's.
		placement = saudi_selected_placement("fa04")
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
		frappe.set_user("Administrator")
		log_stage_income(100, "ETB", "test", placement=placement.name)

		finance_manager = make_role_user("fa05", "Finance Manager")
		frappe.set_user(finance_manager.name)
		visible = frappe.get_list("Applicant Transaction")
		self.assertGreaterEqual(len(visible), 1)

	def test_approve_transaction_requires_finance_role(self):
		placement = saudi_selected_placement("fa06")
		result = log_stage_income(100, "ETB", "test", placement=placement.name)

		officer = make_role_user("fa06", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			approve_transaction(result["name"])

	def test_approve_transaction_succeeds(self):
		placement = saudi_selected_placement("fa06b")
		result = log_stage_income(100, "ETB", "test", placement=placement.name)

		approved = approve_transaction(result["name"])
		self.assertEqual(approved["status"], "Approved")
		self.assertEqual(approved["approved_by"], "Administrator")

	def test_reject_transaction_requires_reason(self):
		placement = saudi_selected_placement("fa06c")
		result = log_stage_income(100, "ETB", "test", placement=placement.name)

		with self.assertRaises(frappe.ValidationError):
			reject_transaction(result["name"], "")

	def test_reject_transaction_succeeds(self):
		placement = saudi_selected_placement("fa06d")
		result = log_stage_income(100, "ETB", "test", placement=placement.name)

		rejected = reject_transaction(result["name"], "Duplicate entry")
		self.assertEqual(rejected["status"], "Rejected")
		self.assertEqual(rejected["rejection_reason"], "Duplicate entry")

	def test_void_transaction_requires_reason(self):
		placement = saudi_selected_placement("fa07")
		result = log_stage_income(100, "ETB", "test", placement=placement.name)
		approve_transaction(result["name"])

		with self.assertRaises(frappe.ValidationError):
			void_transaction(result["name"], "")

	def test_void_transaction_requires_finance_role(self):
		placement = saudi_selected_placement("fa08")
		result = log_stage_income(100, "ETB", "test", placement=placement.name)
		approve_transaction(result["name"])

		officer = make_role_user("fa08", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			void_transaction(result["name"], "Entered in error")

	def test_void_transaction_only_from_approved(self):
		placement = saudi_selected_placement("fa08b")
		result = log_stage_income(100, "ETB", "test", placement=placement.name)
		with self.assertRaises(frappe.ValidationError):
			void_transaction(result["name"], "Entered in error")

	def test_void_transaction_succeeds_and_stays_visible(self):
		placement = saudi_selected_placement("fa09")
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

	def _two_item_batch(self, tag):
		"""Two placements sharing one Contractor+country, each with an owed commission --
		lets batch-level tests exercise partial (some items Paid, some Pending) settlement,
		which a single-item batch can't distinguish from full settlement."""
		from agency_tracking.agency_tracking.doctype.placement.test_placement import (
			make_contractor,
			registered_applicant,
		)

		record_fx_rate("USD", 55.0, frappe.utils.today())
		contractor = make_contractor(tag, country="Saudi Arabia")
		placements = []
		for suffix in ("a", "b"):
			applicant = registered_applicant(f"{tag}{suffix}", entry_track="Muayena", destination_country="Saudi Arabia")
			placement = frappe.get_doc(
				{
					"doctype": "Placement",
					"applicant": applicant.name,
					"contractor": contractor.name,
					"destination_country": "Saudi Arabia",
					"status": "Selected",
					"medical_selected_status": "FIT",
					"manual_commission_amount": 300,
					"manual_commission_currency": "USD",
				}
			).insert(ignore_permissions=True)
			frappe.db.set_value("Applicant", applicant.name, "active_placement", placement.name)
			trigger_early_commission_accrual(placement.name)
			placements.append(placement)
		batch = create_commission_batch(contractor.name, "Saudi Arabia")
		return batch, placements

	def test_settle_batch_items_marks_specific_items_paid_and_batch_partially_settled(self):
		# backend-issues #09 (AGREED_SPEC.md Part 7.3): settle_batch (whole-batch) is joined by
		# an explicit multi-select path -- a batch can now be partially paid.
		batch, _ = self._two_item_batch("fa14")
		self.assertEqual(len(batch["items"]), 2)
		first_item = batch["items"][0]["name"]

		officer = make_role_user("fa14", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			settle_batch_items([first_item])

		frappe.set_user("Administrator")
		result = settle_batch_items([first_item])
		self.assertEqual(result["updated_items"], [first_item])

		refreshed = frappe.get_doc("Commission Batch Request", batch["name"])
		self.assertEqual(refreshed.status, "Partially Settled")

	def test_upload_batch_payment_proof_matches_by_applicant_name(self):
		batch, placements = self._two_item_batch("fa15")
		matched_applicant = frappe.db.get_value("Placement", placements[0].name, "applicant")
		matched_name = frappe.db.get_value("Applicant", matched_applicant, "full_name")

		file_url = write_names_csv("fa15-paid.csv", [matched_name])
		result = upload_batch_payment_proof(batch["name"], file_url)
		self.assertEqual(len(result["matched_items"]), 1)

		refreshed = frappe.get_doc("Commission Batch Request", batch["name"])
		self.assertEqual(refreshed.status, "Partially Settled")

	def test_get_batch_invoice_pdf_requires_finance_role(self):
		batch, _ = self._two_item_batch("fa16")

		officer = make_role_user("fa16", "Clearance Officer")
		frappe.set_user(officer.name)
		with self.assertRaises(frappe.PermissionError):
			get_batch_invoice_pdf(batch["name"])

		frappe.set_user("Administrator")
		get_batch_invoice_pdf(batch["name"])
		self.assertEqual(frappe.local.response.type, "pdf")
		self.assertTrue(frappe.local.response.filecontent)
