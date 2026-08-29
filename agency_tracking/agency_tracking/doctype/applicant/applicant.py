# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document

# Part A.2 / business-workflow-srs.md Stage 1: bare minimum to open a file. Registrar-confirmed
# floor (2026-08-29): phone/address are NOT required at Draft -- only identity + which track.
DRAFT_REQUIRED_FIELDS = ["full_name", "gender", "nationality", "entry_track"]

# Part A.2 / SRS Stage 2 (Standard track): full field floor before a candidate is "official".
# national_id, labor_id, emergency_contact_name/phone are deliberately NOT required here
# (2026-08-29 correction) -- those are LMIS-stage data, captured later via
# applicant_api.update_applicant_for_lmis once the candidate reaches the LMIS clearance step,
# not known/collected at Registration time.
STANDARD_REGISTERED_REQUIRED_FIELDS = DRAFT_REQUIRED_FIELDS + [
	"destination_country",
	"salary_amount",
	"salary_currency",
	"religion",
	"marital_status",
	"passport_number",
	"passport_issue_date",
	"passport_expiry_date",
	"passport_issue_place",
	"date_of_birth",
	"education",
	"target_job",
	"photograph",
	"passport_scan",
]

# Part A.1: Muayena registers with a lighter, global-only field floor
# (passport, medical, photos — CV-specific fields optional/unused; national_id is LMIS-stage,
# same reasoning as Standard above).
# destination_country IS required here (2026-08-29 correction) -- it's selected during
# Draft/Registered same as Standard, not deferred until a contract is uploaded. The earlier
# assumption that it becomes known only at Placement creation was wrong; see
# placement_api.create_muayena_placement, which no longer needs to set it as a side effect.
MUAYENA_REGISTERED_REQUIRED_FIELDS = DRAFT_REQUIRED_FIELDS + [
	"destination_country",
	"passport_number",
	"passport_issue_date",
	"passport_expiry_date",
	"passport_issue_place",
	"date_of_birth",
	"photograph",
	"passport_scan",
]

FIELD_FLOOR = {
	("Standard", "Draft"): DRAFT_REQUIRED_FIELDS,
	("Standard", "Registered"): STANDARD_REGISTERED_REQUIRED_FIELDS,
	("Muayena", "Draft"): DRAFT_REQUIRED_FIELDS,
	("Muayena", "Registered"): MUAYENA_REGISTERED_REQUIRED_FIELDS,
}

# Fields whose uniqueness is enforced manually (see validate_uniqueness) rather than via
# a DB-level `unique` flag, since they're blank at Draft and a DB unique index would collide
# on repeated empty strings across multiple Draft rows.
UNIQUE_FIELDS = ["passport_number", "national_id", "labor_id"]


class Applicant(Document):
	def before_validate(self):
		# Must run before validate() (Frappe's save order is before_validate -> validate ->
		# before_save), not before_save -- a before_save hook fires *after* validate_field_floor
		# has already run and thrown, so any field the OCR would have filled in is too late to
		# help this same save. Found 2026-08-29 via a real "uploading a passport on a
		# near-empty Draft throws a field-floor error" report.
		self.autofill_from_passport()
		self.calc_passport_issue_date()
		self.calc_age()

	def validate(self):
		self.set_full_name()
		self.validate_field_floor()
		self.validate_uniqueness()

	def before_save(self):
		self.maybe_log_fee_transaction()
		self.sync_fee_log()

	def autofill_from_passport(self):
		"""Auto-parse the passport scan's MRZ on upload and fill in currently-blank fields
		only -- never overwrites something the registrar already typed. Best-effort
		convenience, never blocks the save (see passport_parser.parse_passport_mrz)."""
		if not (self.passport_scan and self.has_value_changed("passport_scan")):
			return
		try:
			from agency_tracking.passport_parser import parse_passport_mrz

			file_doc = frappe.db.get_value("File", {"file_url": self.passport_scan}, "name")
			if not file_doc:
				return
			file_path = frappe.get_doc("File", file_doc).get_full_path()
			extracted = parse_passport_mrz(file_path)
		except Exception:
			frappe.log_error(title="Passport auto-fill failed", message=f"Applicant {self.name}")
			return

		if not extracted:
			return

		# first_name/last_name is a joint condition -- only split into the pair if BOTH are
		# currently blank, never partially overwrite one half of an already-entered name.
		if "first_name" in extracted or "last_name" in extracted:
			if self.first_name or self.last_name:
				extracted.pop("first_name", None)
				extracted.pop("last_name", None)

		for fieldname, value in extracted.items():
			if not self.get(fieldname):
				self.set(fieldname, value)

	def calc_passport_issue_date(self):
		"""Passport Issue Date is fully derived, never manually entered (2026-08-29 correction,
		read_only in applicant.json) -- Ethiopian passports have a fixed 5-year validity, so
		issue date = expiry date - 5 years. Reuses the same pure function passport_parser.py's
		MRZ path already uses, so OCR and direct entry agree."""
		if not self.passport_expiry_date:
			return
		from agency_tracking.passport_parser import infer_passport_issue_date

		self.passport_issue_date = infer_passport_issue_date(self.passport_expiry_date)

	def calc_age(self):
		"""Age is fully derived from Date of Birth (2026-08-29, read_only in applicant.json) --
		never manually entered."""
		if not self.date_of_birth:
			self.age = None
			return
		dob = frappe.utils.getdate(self.date_of_birth)
		today = frappe.utils.getdate()
		self.age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

	def set_full_name(self):
		"""Some clients (the split-name intake form) never set full_name directly --
		derive it from first/middle/last whenever full_name itself is blank. Clients that
		already send full_name directly (e.g. the built-in SPA) are untouched."""
		if not self.full_name and self.first_name:
			self.full_name = " ".join(filter(None, [self.first_name, self.middle_name, self.last_name]))

	def validate_field_floor(self):
		required = FIELD_FLOOR.get((self.entry_track, self.status))
		if required is None:
			# CV Generated and beyond: field floor was already enforced on the way into
			# Registered; nothing new is required to hold that status.
			return
		missing = [
			frappe.get_meta(self.doctype).get_label(fieldname)
			for fieldname in required
			if not self.get(fieldname)
		]
		if missing:
			frappe.throw(
				"{0} track, {1} status requires: {2}".format(
					self.entry_track, self.status, ", ".join(missing)
				),
				frappe.ValidationError,
			)

	def validate_uniqueness(self):
		for fieldname in UNIQUE_FIELDS:
			value = self.get(fieldname)
			if not value:
				continue
			existing = frappe.db.get_value(
				self.doctype,
				{fieldname: value, "name": ["!=", self.name or ""]},
				"name",
			)
			if existing:
				frappe.throw(
					"Another {0} ({1}) already has {2} '{3}'.".format(
						self.doctype, existing, frappe.get_meta(self.doctype).get_label(fieldname), value
					),
					frappe.DuplicateEntryError,
				)

	def maybe_log_fee_transaction(self):
		"""Fires the moment fee_status flips to Paid (button-driven or a direct Desk edit) --
		one single path for both, since log_applicant_fee (applicant_api.py) just sets
		fee_status='Paid' and saves, letting this hook do the actual logging. Idempotent via
		fee_transaction (never re-logs once set) and has_value_changed (never fires on an
		unrelated save of an already-Paid row)."""
		if not (
			self.fee_required
			and self.registration_fee_amount
			and self.fee_status == "Paid"
			and not self.fee_transaction
			and self.has_value_changed("fee_status")
		):
			return

		from agency_tracking.finance_engine import get_fx_rate

		fx_rate, fx_rate_date = get_fx_rate(self.fee_currency or "ETB")
		txn = frappe.get_doc(
			{
				"doctype": "Applicant Transaction",
				"applicant": self.name,
				"placement": self.active_placement or None,
				"transaction_type": self.fee_direction or "Income",
				"amount_original": self.registration_fee_amount,
				"currency_original": self.fee_currency or "ETB",
				"fx_rate": fx_rate,
				"fx_rate_date": fx_rate_date,
				"amount_birr": round(float(self.registration_fee_amount) * fx_rate, 2),
				"description": (self.fee_type or "Registration Fee")
				+ f" for {self.name}"
				+ (f" -- {self.fee_notes}" if self.fee_notes else ""),
				"stage_logged_at": self.status,
				"logged_by": frappe.session.user,
			}
		).insert(ignore_permissions=True)

		self.fee_transaction = txn.name
		if not self.fee_payment_date:
			self.fee_payment_date = frappe.utils.today()

	def sync_fee_log(self):
		"""Table-based income/expense log (2026-08-29) -- unlike the single Registration Fee
		above, this allows any number of entries per applicant. Every row without a linked
		transaction yet gets auto-logged as a Pending Applicant Transaction on this save (no
		separate button/endpoint needed, same as maybe_log_fee_transaction); every row that
		already has one gets its Status refreshed from the ledger's current state, so Finance
		approving/rejecting/voiding on the Applicant Transaction itself is reflected back here
		without the row itself ever needing another edit."""
		from agency_tracking.agency_tracking.storage_engine import migrate_attach_to_r2
		from agency_tracking.finance_engine import get_fx_rate

		for row in self.get("fee_log") or []:
			migrate_attach_to_r2(row, "receipt_url", "finance-receipts", applicant_name=self.name)

			if row.transaction:
				row.status = frappe.db.get_value("Applicant Transaction", row.transaction, "status") or row.status
				continue

			if not (row.description and row.amount):
				continue

			fx_rate, fx_rate_date = get_fx_rate(row.currency or "ETB")
			txn = frappe.get_doc(
				{
					"doctype": "Applicant Transaction",
					"applicant": self.name,
					"placement": self.active_placement or None,
					"transaction_type": row.transaction_type or "Income",
					"amount_original": row.amount,
					"currency_original": row.currency or "ETB",
					"fx_rate": fx_rate,
					"fx_rate_date": fx_rate_date,
					"amount_birr": round(float(row.amount) * fx_rate, 2),
					"description": row.description,
					"stage_logged_at": self.status,
					"logged_by": frappe.session.user,
				}
			).insert(ignore_permissions=True)
			row.transaction = txn.name
			row.status = "Pending"
