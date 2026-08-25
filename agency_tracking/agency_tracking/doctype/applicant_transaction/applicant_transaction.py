# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document


class ApplicantTransaction(Document):
	def validate(self):
		# Defense in depth: amount_birr must always be the product of the two figures that
		# produced it, regardless of which code path created this row.
		self.amount_birr = round((self.amount_original or 0) * (self.fx_rate or 0), 2)


def get_permission_query_conditions(user):
	"""Part D: "1=0 permission query condition for everyone except Finance Manager/Admin; not
	a soft filter, a hard zero." Belt-and-suspenders alongside the doctype-level permissions
	(which already grant read only to Finance Manager/Admin/System Manager) — if a future step
	ever broadens doctype-level read, this still holds the line."""
	if not user:
		user = frappe.session.user
	if {"Finance Manager", "Admin"} & set(frappe.get_roles(user)):
		return ""
	return "1=0"
