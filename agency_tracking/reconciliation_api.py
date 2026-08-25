# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part F: module-scoped whitelisted functions, no raw /api/resource/* exposure.

import frappe

from agency_tracking.finance_engine import settle_batch_request
from agency_tracking.reconciliation_engine import match_statement_lines, parse_bank_statement_csv


def _require_finance_role():
	if not ({"Finance Manager", "Admin"} & set(frappe.get_roles())):
		frappe.throw("Not permitted.", frappe.PermissionError)


@frappe.whitelist()
def upload_bank_statement(file_url):
	_require_finance_role()
	rows = parse_bank_statement_csv(file_url)
	statement = frappe.get_doc(
		{
			"doctype": "Bank Statement",
			"statement_file": file_url,
			"uploaded_by": frappe.session.user,
			"status": "Uploaded",
			"lines": rows,
		}
	).insert(ignore_permissions=True)
	match_statement_lines(statement)
	return statement.as_dict()


@frappe.whitelist()
def manually_match_line(statement_line_name, batch_name):
	"""Escape hatch for lines the automatic matcher couldn't confidently resolve (ambiguous
	amount collisions, missing reference text) — Finance Manager/Admin only, same shape as
	every other manual-override path in this build."""
	_require_finance_role()
	line = frappe.get_doc("Bank Statement Line", statement_line_name)
	line.matched_batch = batch_name
	line.match_status = "Manually Matched"
	line.save(ignore_permissions=True)
	settle_batch_request(batch_name, line.reference or f"Manually matched: {statement_line_name}")
	return line.as_dict()
