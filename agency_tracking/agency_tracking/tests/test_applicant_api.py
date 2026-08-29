# Copyright (c) 2026, Agency and contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from agency_tracking.applicant_api import log_applicant_fee, update_applicant_for_lmis
from agency_tracking.finance_api import approve_transaction
from agency_tracking.state_machine import transition


def standard_floor_without_lmis_fields(tag):
	"""national_id/labor_id/emergency_contact_* are LMIS-stage data (2026-08-29 correction) --
	not part of the Registered floor, deliberately omitted here."""
	return {
		"destination_country": "Saudi Arabia",
		"salary_amount": 1500,
		"salary_currency": "SAR",
		"religion": "Muslim",
		"marital_status": "Single",
		"passport_number": f"EP-LMIS-{tag}",
		"passport_issue_date": "2024-01-01",
		"passport_expiry_date": "2029-01-01",
		"passport_issue_place": "Addis Ababa",
		"date_of_birth": "1998-01-01",
		"education": "High School",
		"target_job": "Housemaid",
		"photograph": "/files/test_photo.jpg",
		"passport_scan": "/files/test_passport.pdf",
		"medical_status": "FIT",
	}


def registered_applicant_no_lmis_fields(tag):
	doc = frappe.get_doc(
		{
			"doctype": "Applicant",
			"entry_track": "Standard",
			"full_name": "LMIS Test Person",
			"gender": "Female",
			"nationality": "Ethiopia",
			**standard_floor_without_lmis_fields(tag),
		}
	).insert(ignore_permissions=True)
	transition(doc, "Registered")
	return doc


class TestApplicantAPI(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_standard_registers_without_national_id_labor_id_or_emergency_contact(self):
		doc = registered_applicant_no_lmis_fields("aa01")
		self.assertEqual(doc.status, "Registered")
		self.assertFalse(doc.national_id)
		self.assertFalse(doc.labor_id)
		self.assertFalse(doc.emergency_contact_name)

	def test_update_applicant_for_lmis_sets_national_id_and_labor_id(self):
		doc = registered_applicant_no_lmis_fields("aa02")
		frappe.set_user("Administrator")

		result = update_applicant_for_lmis(
			doc.name,
			national_id="NID-AA02",
			labor_id="LAB-AA02",
			emergency_contact_name="Abebe Bekele",
			emergency_contact_phone="+251911111111",
		)
		self.assertEqual(result["national_id"], "NID-AA02")
		self.assertEqual(result["labor_id"], "LAB-AA02")
		self.assertEqual(result["emergency_contact_name"], "Abebe Bekele")

	def test_update_applicant_for_lmis_ignores_fields_outside_its_allowlist(self):
		doc = registered_applicant_no_lmis_fields("aa03")
		frappe.set_user("Administrator")

		result = update_applicant_for_lmis(doc.name, national_id="NID-AA03", target_job="Cook")
		self.assertEqual(result["national_id"], "NID-AA03")
		self.assertEqual(result["target_job"], "Housemaid")

	def test_update_applicant_for_lmis_blocked_for_unrelated_role(self):
		doc = registered_applicant_no_lmis_fields("aa04")
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "aa04-registrar@example.com",
				"first_name": "Registrar",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		user.add_roles("Registrar")
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			update_applicant_for_lmis(doc.name, national_id="NID-AA04")

	def test_setting_fee_status_to_paid_auto_logs_ledger_entry(self):
		doc = registered_applicant_no_lmis_fields("aa05")
		doc.fee_required = 1
		doc.registration_fee_amount = 500
		doc.fee_currency = "ETB"
		doc.fee_type = "Registration Fee"
		doc.fee_status = "Paid"
		doc.save(ignore_permissions=True)

		self.assertTrue(doc.fee_transaction)
		txn = frappe.get_doc("Applicant Transaction", doc.fee_transaction)
		self.assertEqual(txn.applicant, doc.name)
		self.assertEqual(txn.amount_original, 500)
		self.assertEqual(txn.transaction_type, "Income")
		self.assertTrue(doc.fee_payment_date)

	def test_fee_status_paid_twice_does_not_double_log(self):
		doc = registered_applicant_no_lmis_fields("aa06")
		doc.fee_required = 1
		doc.registration_fee_amount = 300
		doc.fee_currency = "ETB"
		doc.fee_status = "Paid"
		doc.save(ignore_permissions=True)
		first_txn = doc.fee_transaction

		doc.fee_notes = "unrelated edit"
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.fee_transaction, first_txn)
		self.assertEqual(
			frappe.db.count("Applicant Transaction", {"applicant": doc.name}), 1
		)

	def test_log_applicant_fee_button_path(self):
		doc = registered_applicant_no_lmis_fields("aa07")
		doc.fee_required = 1
		doc.registration_fee_amount = 400
		doc.fee_currency = "ETB"
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.fee_status, "Pending")

		result = log_applicant_fee(doc.name)
		self.assertEqual(result["fee_status"], "Paid")
		self.assertTrue(result["fee_transaction"])

	def test_log_applicant_fee_rejects_already_logged(self):
		doc = registered_applicant_no_lmis_fields("aa08")
		doc.fee_required = 1
		doc.registration_fee_amount = 250
		doc.fee_currency = "ETB"
		doc.save(ignore_permissions=True)
		log_applicant_fee(doc.name)

		with self.assertRaises(frappe.ValidationError):
			log_applicant_fee(doc.name)

	def test_log_applicant_fee_requires_amount(self):
		doc = registered_applicant_no_lmis_fields("aa09")
		doc.fee_required = 1
		doc.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			log_applicant_fee(doc.name)

	def test_fee_log_table_auto_logs_multiple_rows(self):
		doc = registered_applicant_no_lmis_fields("aa10")
		doc.append("fee_log", {"description": "Medical exam fee", "transaction_type": "Expense", "amount": 200})
		doc.append("fee_log", {"description": "Late walk-in surcharge", "transaction_type": "Income", "amount": 50})
		doc.save(ignore_permissions=True)

		self.assertEqual(len(doc.fee_log), 2)
		for row in doc.fee_log:
			self.assertTrue(row.transaction)
			self.assertEqual(row.status, "Pending")
		self.assertEqual(
			frappe.db.count("Applicant Transaction", {"applicant": doc.name, "status": "Pending"}), 2
		)

	def test_fee_log_row_not_re_logged_on_later_save(self):
		doc = registered_applicant_no_lmis_fields("aa11")
		doc.append("fee_log", {"description": "Injaz appointment fee", "transaction_type": "Expense", "amount": 75})
		doc.save(ignore_permissions=True)
		first_txn = doc.fee_log[0].transaction

		doc.remarks = "unrelated edit"
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.fee_log[0].transaction, first_txn)
		self.assertEqual(frappe.db.count("Applicant Transaction", {"applicant": doc.name}), 1)

	def test_fee_log_status_reflects_finance_approval(self):
		doc = registered_applicant_no_lmis_fields("aa12")
		doc.append("fee_log", {"description": "Wakala reimbursement", "transaction_type": "Income", "amount": 120})
		doc.save(ignore_permissions=True)

		approve_transaction(doc.fee_log[0].transaction)

		doc.reload()
		doc.remarks = "trigger a resave to pull the refreshed status"
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.fee_log[0].status, "Approved")

	def test_fee_log_row_missing_amount_blocked_by_mandatory_field(self):
		# description/transaction_type/amount are reqd=1 on Applicant Fee Log -- Frappe itself
		# blocks an incomplete row before sync_fee_log ever runs, so there's no such thing as
		# a partially-filled row sitting around as "Not Logged".
		doc = registered_applicant_no_lmis_fields("aa13")
		doc.append("fee_log", {"description": "Placeholder, amount not entered yet"})
		with self.assertRaises(frappe.MandatoryError):
			doc.save(ignore_permissions=True)
