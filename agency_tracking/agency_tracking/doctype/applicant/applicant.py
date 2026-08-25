# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document

# Part A.2 / business-workflow-srs.md Stage 1: bare minimum to open a file.
DRAFT_REQUIRED_FIELDS = ["full_name", "gender", "nationality", "phone", "address"]

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
MUAYENA_REGISTERED_REQUIRED_FIELDS = DRAFT_REQUIRED_FIELDS + [
	"national_id",
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
UNIQUE_FIELDS = ["passport_number", "national_id"]


class Applicant(Document):
	def validate(self):
		self.validate_field_floor()
		self.validate_medical_for_registration()
		self.validate_uniqueness()

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
