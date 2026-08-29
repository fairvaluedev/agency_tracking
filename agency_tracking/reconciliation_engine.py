# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part I Step 9 / business-workflow-srs.md Part 6: "Official bank/payment statements can be
# uploaded and matched automatically against what's owed, so nothing gets lost in the gap
# between 'candidate sent' and 'money actually collected.'"
#
# Scope note: the spec doesn't describe a specific bank's file format, so this defines its own
# — a plain CSV (date, reference, amount in Birr) — rather than guessing at a real bank's export
# layout with no sample to build against. That would be exactly the kind of unverifiable,
# speculative parsing this project has deliberately avoided elsewhere (see contract_parser.py's
# Step 4 scope note). Matching itself (amount + reference-text disambiguation) is the real,
# testable, load-bearing part.

import csv

import frappe

from agency_tracking.finance_engine import settle_batch_request

AMOUNT_TOLERANCE = 0.01


def _resolve_frappe_file_path(file_url):
	import os

	if not file_url:
		return None
	clean = str(file_url).lstrip("/")
	if clean.startswith("private/files/"):
		path = frappe.get_site_path("private", "files", os.path.basename(clean))
	else:
		path = frappe.get_site_path("public", "files", os.path.basename(clean))
	return path if os.path.exists(path) else None


def parse_bank_statement_csv(file_url):
	"""Reads a CSV with columns date, reference, amount. Skips malformed rows rather than
	failing the whole import — one bad line in a hundred shouldn't block the rest."""
	file_path = _resolve_frappe_file_path(file_url)
	if not file_path:
		frappe.throw(f"Could not find statement file for {file_url}.", frappe.ValidationError)

	rows = []
	with open(file_path, newline="", encoding="utf-8") as f:
		reader = csv.DictReader(f)
		for raw_row in reader:
			try:
				rows.append(
					{
						"statement_date": raw_row["date"].strip(),
						"reference": (raw_row.get("reference") or "").strip(),
						"amount": float(raw_row["amount"]),
					}
				)
			except (KeyError, ValueError, AttributeError):
				continue
	return rows


def _contractor_name(contractor_name):
	return frappe.db.get_value("Contractor", contractor_name, "contractor_name") or ""


def match_statement_lines(statement):
	"""For each Unmatched line: find unsettled Commission Batch Requests whose total matches
	the line's amount within AMOUNT_TOLERANCE. If exactly one candidate, or exactly one whose
	batch name or contractor name appears in the line's reference text, match and settle it —
	Part A.6's "matched automatically". Anything more ambiguous than that is left Unmatched for
	a Finance Manager to resolve via manually_match_line() rather than guessed at.
	"""
	unsettled_batches = frappe.get_all(
		"Commission Batch Request",
		filters={"status": ["!=", "Settled"]},
		fields=["name", "total_amount_birr", "contractor"],
	)

	for line in statement.lines:
		if line.match_status != "Unmatched":
			continue

		candidates = [b for b in unsettled_batches if abs(b.total_amount_birr - line.amount) <= AMOUNT_TOLERANCE]
		if not candidates:
			continue

		match = None
		if len(candidates) == 1:
			match = candidates[0]
		else:
			reference_text = (line.reference or "").lower()
			narrowed = [
				b
				for b in candidates
				if b.name.lower() in reference_text or _contractor_name(b.contractor).lower() in reference_text
			]
			if len(narrowed) == 1:
				match = narrowed[0]

		if match:
			line.matched_batch = match.name
			line.match_status = "Matched"
			settle_batch_request(match.name, line.reference or f"Auto-matched: {statement.name}")
			unsettled_batches = [b for b in unsettled_batches if b.name != match.name]

	statement.save(ignore_permissions=True)
	return statement


# --- Commission batch paid-applicant-list parsing (2026-08-29) ---
# A distinct feature from the bank-statement reconciliation above: the agency sends a CSV or
# PDF listing which specific applicants they've paid for (not a bank statement line matching a
# batch's total), enabling partial (per-item) settlement -- see finance_engine.
# match_batch_payment_proof.


def _parse_paid_names_csv(file_path):
	"""A single-column (or first-column) CSV of applicant full names, one per row."""
	names = []
	with open(file_path, newline="", encoding="utf-8") as f:
		reader = csv.reader(f)
		for row in reader:
			if row and row[0].strip():
				names.append(row[0].strip())
	return names


def _parse_paid_names_pdf(file_path):
	"""Best-effort: one applicant name per non-empty line of extracted text. No structured
	format to rely on, unlike the bank-statement CSV -- genuinely best-effort, same philosophy
	as contract_parser.py's extraction."""
	from agency_tracking.contract_parser import extract_text_from_pdf

	text = extract_text_from_pdf(file_path)
	return [line.strip() for line in text.splitlines() if line.strip()]


def parse_paid_applicant_names(file_url):
	"""Returns a list of applicant full names from an uploaded CSV or PDF, by extension.
	Missing/unreadable files yield an empty list rather than raising -- unmatched/empty just
	means every item stays Pending for manual review."""
	file_path = _resolve_frappe_file_path(file_url)
	if not file_path:
		return []
	if file_path.lower().endswith(".csv"):
		return _parse_paid_names_csv(file_path)
	return _parse_paid_names_pdf(file_path)
