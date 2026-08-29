# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document

# Part A.2 / business-workflow-srs.md Stage 1: bare minimum to open a file. Registrar-confirmed
# floor (2026-08-29): phone/address are NOT required at Draft -- only identity + which track.
DRAFT_REQUIRED_FIELDS = ["full_name", "gender", "nationality", "entry_track"]

# Part A.2 / SRS Stage 2 (Standard track): full field floor before a candidate is "official".
STANDARD_REGISTERED_REQUIRED_FIELDS = DRAFT_REQUIRED_FIELDS + [
	"national_id",
	"labor_id",
	"destination_country",
	"salary_amount",
	"salary_currency",
	"religion",
	"marital_status",
	"emergency_contact_name",
	"emergency_contact_phone",
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
# (passport, national ID, medical, photos — CV-specific fields optional/unused).
# destination_country IS required here (2026-08-29 correction) -- it's selected during
# Draft/Registered same as Standard, not deferred until a contract is uploaded. The earlier
# assumption that it becomes known only at Placement creation was wrong; see
# placement_api.create_muayena_placement, which no longer needs to set it as a side effect.
MUAYENA_REGISTERED_REQUIRED_FIELDS = DRAFT_REQUIRED_FIELDS + [
	"national_id",
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

	def validate(self):
		self.set_full_name()
		self.validate_field_floor()
		self.validate_medical_for_registration()
		self.validate_uniqueness()

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

	def validate_medical_for_registration(self):
		if self.status in ("Registered", "CV Generated") and self.medical_status != "FIT":
			frappe.throw(
				"Medical status must be FIT before an applicant can be Registered.",
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
