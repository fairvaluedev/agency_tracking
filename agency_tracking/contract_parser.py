# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Part H: "PyMuPDF for text/layout extraction... regex-templated structurizers per contract
# format (Musaned, Kuwait)." Scoped deliberately narrow: the only Placement field the spec ties
# to contract parsing is contract_signed_date (Part A.4: "extracted at parse time, not creation
# date"). Not attempting broad employer/sponsor/agency field extraction — Placement has no
# fields for that data and nothing in Part B/master spec calls for storing it, so building that
# out now would be exactly the kind of speculative extra surface the project guidelines say to
# avoid. Extend with more extraction targets only when a spec'd field actually needs one.

import os
import re

import frappe
from frappe.utils import getdate

DATE_PATTERNS = [
	# English: "Contract Date: 13/08/2026", "Date of Agreement - 2026-08-13"
	r'(?:contract\s*date|agreement\s*date|date\s*of\s*agreement|signed\s*on|signing\s*date)'
	r'\s*[:=\-–]?\s*\(?([0-9]{1,4}[-/.][0-9]{1,2}[-/.][0-9]{1,4})\)?',
	# Arabic: "تاريخ العقد", "تاريخ توقيع العقد", "بتاريخ"
	r'(?:تاريخ\s*العقد|'
	r'تاريخ\s*توقيع\s*العقد|'
	r'بتاريخ)'
	r'\s*[:=\-–]?\s*\(?([0-9]{1,4}[-/.][0-9]{1,2}[-/.][0-9]{1,4})\)?',
]


def normalize_date_string(date_str):
	"""Converts DD/MM/YYYY, YYYY-MM-DD, DD.MM.YYYY etc. to an ISO date string."""
	if not date_str:
		return None
	raw = str(date_str).strip().replace("/", "-").replace(".", "-")
	parts = raw.split("-")
	if len(parts) != 3:
		return None
	try:
		if len(parts[0]) == 4:
			year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
		else:
			day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
		return str(getdate(f"{year:04d}-{month:02d}-{day:02d}"))
	except Exception:
		return None


def extract_contract_signed_date(text):
	"""Best-effort extraction of the contract's own signed date from raw contract text."""
	if not text:
		return None
	for pattern in DATE_PATTERNS:
		match = re.search(pattern, text, re.IGNORECASE)
		if match:
			normalized = normalize_date_string(match.group(1))
			if normalized:
				return normalized
	return None


def extract_text_from_pdf(file_path):
	"""Extracts plain text from a PDF using PyMuPDF. Returns "" if the file can't be read —
	callers treat a missing date as "needs manual entry", not a hard failure, since OCR/layout
	extraction on real-world scanned contracts is inherently best-effort."""
	if not file_path or not os.path.exists(file_path):
		return ""
	try:
		import pymupdf as fitz
	except ImportError:
		try:
			import fitz
		except ImportError:
			return ""
	try:
		text_parts = []
		with fitz.open(file_path) as doc:
			for page in doc:
				text_parts.append(page.get_text())
		return "\n".join(text_parts)
	except Exception:
		return ""


def _resolve_frappe_file_path(file_url):
	"""Translates a Frappe file_url (/files/... or /private/files/...) to a filesystem path."""
	if not file_url:
		return None
	clean = str(file_url).lstrip("/")
	if clean.startswith("private/files/"):
		path = frappe.get_site_path("private", "files", os.path.basename(clean))
	else:
		path = frappe.get_site_path("public", "files", os.path.basename(clean))
	return path if os.path.exists(path) else None


def parse_contract_file(file_url):
	"""Given a Frappe file_url for an uploaded contract, returns {"contract_signed_date": ...}.
	Missing/unreadable files or dates the regexes don't match yield None, not an exception —
	staff can always enter the date manually; parsing is a convenience, not a hard gate."""
	file_path = _resolve_frappe_file_path(file_url)
	text = extract_text_from_pdf(file_path) if file_path else ""
	return {"contract_signed_date": extract_contract_signed_date(text)}
