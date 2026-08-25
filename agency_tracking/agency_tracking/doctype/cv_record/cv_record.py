# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from agency_tracking.state_machine import musaned_gate_passed


class CVRecord(Document):
	def validate(self):
		applicant = frappe.get_doc("Applicant", self.applicant)

		if applicant.entry_track != "Standard":
			frappe.throw(
				"CV Record does not apply to Muayena candidates (Part A.1) — "
				f"{applicant.name} is entry track '{applicant.entry_track}'.",
				frappe.ValidationError,
			)

		if applicant.status != "Registered":
			frappe.throw(
				f"Applicant {applicant.name} must be Registered before a CV can be generated "
				f"(currently '{applicant.status}').",
				frappe.ValidationError,
			)

		if not musaned_gate_passed(applicant):
			frappe.throw(
				f"Musaned gate not passed for {applicant.name}: status is "
				f"'{applicant.musaned_status}', must be 'ALTEYAZECHEM' before CV generation "
				"(Saudi-bound Standard candidates only, Part A.2).",
				frappe.ValidationError,
			)

	def before_insert(self):
		self.generated_on = now_datetime()
		self.generated_by = frappe.session.user
