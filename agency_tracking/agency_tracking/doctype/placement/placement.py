# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document


class Placement(Document):
	def validate(self):
		applicant = frappe.get_doc("Applicant", self.applicant)

		if applicant.entry_track == "Muayena":
			frappe.throw(
				"Muayena Placement creation (direct contract-upload entry) isn't wired in yet "
				"— see Part I Step 4.",
				frappe.ValidationError,
			)

		if applicant.active_placement and applicant.active_placement != self.name:
			frappe.throw(
				f"{applicant.name} already has an active Placement ({applicant.active_placement}).",
				frappe.ValidationError,
			)

		if self.destination_country != applicant.destination_country:
			frappe.throw(
				"Placement destination_country must match the Applicant's destination_country.",
				frappe.ValidationError,
			)
