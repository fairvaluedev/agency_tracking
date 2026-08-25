# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import frappe
from frappe.model.document import Document


class CommissionBatchRequest(Document):
	def validate(self):
		self.total_amount_birr = sum(
			frappe.db.get_value("Applicant Transaction", row.transaction, "amount_birr") or 0
			for row in self.items
		)


def get_permission_query_conditions(user):
	"""Same wall as Applicant Transaction — a batch request is just as sensitive as the
	transactions it groups."""
	if not user:
		user = frappe.session.user
	if {"Finance Manager", "Admin"} & set(frappe.get_roles(user)):
		return ""
	return "1=0"
