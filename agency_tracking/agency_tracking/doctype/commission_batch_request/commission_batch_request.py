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
		self._apply_advance()

	def _apply_advance(self):
		"""A foreign agency sometimes remits only part of a requested batch total up front.
		advance_amount records what actually came in; balance_due_birr is the remainder still
		owed. Any positive advance that doesn't cover the whole total moves a still-open batch
		(Draft/Sent) to Partially Settled -- never downgrades an already Settled batch, and the
		full item-by-item settlement path (finance_engine._sync_batch_status_from_items) stays
		the authority for reaching Settled."""
		advance = self.advance_amount or 0
		total = self.total_amount_birr or 0
		self.balance_due_birr = max(total - advance, 0)
		if advance > 0 and self.status in ("Draft", "Sent"):
			self.status = "Partially Settled"


def get_permission_query_conditions(user):
	"""Same wall as Applicant Transaction — a batch request is just as sensitive as the
	transactions it groups."""
	if not user:
		user = frappe.session.user
	if {"Finance Manager", "Admin"} & set(frappe.get_roles(user)):
		return ""
	return "1=0"
