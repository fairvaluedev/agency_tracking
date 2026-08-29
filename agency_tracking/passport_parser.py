# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import os
import re
import io
import datetime
import unicodedata

import frappe
from frappe.utils import getdate

try:
	from passporteye import read_mrz
except ImportError:
	read_mrz = None

try:
	import pycountry
except ImportError:
	pycountry = None

# ─────────────────────────────────────────────────────────────────────────────
# 1. ISO 3166-1 Alpha-3 Country Mapping & Constants
# ─────────────────────────────────────────────────────────────────────────────
ISO_ALPHA3_TO_COUNTRY = {
	"ETH": "Ethiopia",
	"SAU": "Saudi Arabia",
	"ARE": "United Arab Emirates",
	"KWT": "Kuwait",
	"QAT": "Qatar",
	"BHR": "Bahrain",
	"OMN": "Oman",
	"JOR": "Jordan",
	"LBN": "Lebanon",
	"KEN": "Kenya",
	"UGA": "Uganda",
	"SDN": "Sudan",
	"SSD": "South Sudan",
	"SOM": "Somalia",
	"DJI": "Djibouti",
	"EGY": "Egypt",
	"ERI": "Eritrea",
	"IND": "India",
	"PAK": "Pakistan",
	"BGD": "Bangladesh",
	"PHL": "Philippines",
	"IDN": "Indonesia",
	"NPL": "Nepal",
	"LKA": "Sri Lanka",
	"GBR": "United Kingdom",
	"USA": "United States",
	"CAN": "Canada",
	"AUS": "Australia",
	"DEU": "Germany",
	"FRA": "France",
	"ITA": "Italy",
	"ESP": "Spain",
	"TUR": "Turkey",
	"CHN": "China",
	"JPN": "Japan",
	"YEM": "Yemen",
	"IRQ": "Iraq",
	"SYR": "Syrian Arab Republic",
}

MONTH_MAP = {
	"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
	"JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
}

MRZ_SEX_TO_GENDER = {"M": "Male", "F": "Female"}

# ─────────────────────────────────────────────────────────────────────────────
# 2. ICAO 9303 Checksum Decoder & Self-Correction Engine
# ─────────────────────────────────────────────────────────────────────────────
ICAO_WEIGHTS = [7, 3, 1]

CHAR_CONFUSIONS = {
	"O": ["0", "Q", "D", "U"],
	"0": ["O", "Q", "D", "U"],
	"I": ["1", "l", "|", "T", "J"],
	"1": ["I", "l", "|", "T", "J"],
	"S": ["5", "8", "$"],
	"5": ["S", "6"],
	"B": ["8", "6", "0", "E"],
	"8": ["B", "0", "3", "S"],
	"Z": ["2", "7"],
	"2": ["Z"],
	"G": ["6", "0", "C", "Q"],
	"6": ["G", "b", "5"],
	"D": ["0", "O", "Q"],
	"Q": ["0", "O", "G"],
	"U": ["V", "0"],
	"V": ["U", "<"],
	"K": ["<", "X"],
	"C": ["<", "G", "0"],
	"<": ["K", "C", "X", "(", " ", "_", "-"],
}


def icao_char_value(c):
	"""Returns integer value for ICAO 9303 checksum computation."""
	c = str(c).upper()
	if c.isdigit():
		return int(c)
	if 'A' <= c <= 'Z':
		return ord(c) - ord('A') + 10
	return 0


def compute_icao_checksum(text):
	"""Computes ICAO 9303 checksum digit for a given alphanumeric string."""
	total = 0
	for idx, char in enumerate(text):
		weight = ICAO_WEIGHTS[idx % 3]
		total += icao_char_value(char) * weight
	return total % 10


def verify_and_correct_checksum(data_str, expected_check_char, is_numeric=True):
	"""
	Validates data_str against expected_check_char.
	Uses OCR confusion map to find single character substitutions.
	"""
	data_clean = str(data_str).upper()
	check_char = str(expected_check_char).upper()

	if check_char in ("O", "D", "Q"):
		check_char = "0"
	elif check_char in ("I", "L", "|"):
		check_char = "1"
	elif check_char == "S":
		check_char = "5"
	elif check_char == "B":
		check_char = "8"
	elif check_char == "Z":
		check_char = "2"

	if not check_char.isdigit():
		return False, data_clean, check_char

	expected_check_val = int(check_char)
	computed = compute_icao_checksum(data_clean)

	if computed == expected_check_val and (not is_numeric or data_clean.isdigit()):
		return True, data_clean, str(expected_check_val)

	# Single-character substitution trial
	data_list = list(data_clean)
	positions = list(range(len(data_list)))
	if is_numeric:
		# Prioritize positions that currently contain non-digits
		positions.sort(key=lambda idx: 0 if not data_list[idx].isdigit() else 1)

	for pos in positions:
		ch = data_list[pos]
		confusions = CHAR_CONFUSIONS.get(ch, [])
		for alt in confusions:
			if is_numeric and not alt.isdigit():
				continue
			trial_list = list(data_list)
			trial_list[pos] = alt
			trial_str = "".join(trial_list)
			if is_numeric and not trial_str.isdigit():
				continue
			if compute_icao_checksum(trial_str) == expected_check_val:
				return True, trial_str, str(expected_check_val)

	return False, data_clean, check_char


# ─────────────────────────────────────────────────────────────────────────────
# 3. Clean and Parse MRZ Lines
# ─────────────────────────────────────────────────────────────────────────────
def clean_mrz_line(raw_line):
	"""Cleans noisy characters from an OCR'd MRZ line."""
	if not raw_line:
		return ""
	line = raw_line.strip().upper()
	line = line.replace("«", "<").replace("‹", "<").replace("(", "<").replace(")", "<")
	line = line.replace("{", "<").replace("}", "<").replace("[", "<").replace("]", "<")
	line = line.replace("_", "<").replace("-", "<").replace(" ", "")
	line = re.sub(r'[^A-Z0-9<]', '', line)
	return line


def parse_mrz_date(yymmdd_str, is_expiry=False):
	"""Converts YYMMDD string to YYYY-MM-DD."""
	if not yymmdd_str or len(yymmdd_str) < 6:
		return None
	try:
		yy = int(yymmdd_str[0:2])
		mm = int(yymmdd_str[2:4])
		dd = int(yymmdd_str[4:6])

		if mm < 1 or mm > 12 or dd < 1 or dd > 31:
			return None

		curr_year = datetime.datetime.now().year
		curr_yy = curr_year % 100

		if is_expiry:
			century = 2000 if yy <= curr_yy + 30 else 1900
		else:
			century = 1900 if yy > curr_yy else 2000

		full_year = century + yy
		return f"{full_year:04d}-{mm:02d}-{dd:02d}"
	except Exception:
		return None


def infer_passport_issue_date(passport_expiry_str):
	"""
	Infers passport issue date by subtracting 5 years from passport expiry date.
	e.g. 2030-05-12 -> 2025-05-12
	"""
	if not passport_expiry_str:
		return None
	try:
		from dateutil.relativedelta import relativedelta
		exp_date = getdate(passport_expiry_str)
		return str(exp_date - relativedelta(years=5))
	except Exception:
		return None


def parse_mrz_td3(line1, line2):
	"""
	Parses standard Type 3 (TD3) Passport MRZ (2 lines x 44 characters).
	Example:
	Line 1: PQETHWACHAMO<<ASNEKECH<TEDESSE<<<<<<<<<<<<<<<<
	Line 2: EQ25760963ETH0012027F30051210<<<<<<<<<<<<<<04
	"""
	result = {
		"format": "TD3",
		"doc_type": "Passport",
		"raw_line1": line1,
		"raw_line2": line2,
		"is_valid": True,
		"checksum_validation": {},
	}

	line1 = (line1 + "<" * 44)[:44]
	line2 = (line2 + "<" * 44)[:44]

	# --- Line 1 Breakdown ---
	doc_code = line1[0:2].replace("<", "")
	issuing_country_code = line1[2:5].replace("<", "")
	name_field = line1[5:44]

	name_parts = name_field.split("<<")
	surname = name_parts[0].replace("<", " ").strip()
	given_names = ""
	if len(name_parts) > 1:
		given_names = name_parts[1].replace("<", " ").strip()

	given_split = [p for p in given_names.split() if p]
	first_name = given_split[0] if given_split else ""
	middle_name = " ".join(given_split[1:]) if len(given_split) > 1 else ""
	last_name = surname

	if not middle_name and len(given_split) == 1 and not surname:
		first_name = given_split[0]

	# --- Line 2 Breakdown ---
	raw_doc_num = line2[0:9]
	raw_doc_check = line2[9]
	nationality_code = line2[10:13].replace("<", "")
	raw_dob = line2[13:19]
	raw_dob_check = line2[19]
	sex_char = line2[20].upper()
	raw_expiry = line2[21:27]
	raw_expiry_check = line2[27]
	raw_optional = line2[28:42]

	val_doc, corr_doc_num, corr_doc_check = verify_and_correct_checksum(raw_doc_num, raw_doc_check, is_numeric=False)
	clean_passport_num = corr_doc_num.replace("<", "").strip()
	result["checksum_validation"]["passport_number"] = {
		"valid": val_doc, "raw": raw_doc_num, "clean": clean_passport_num, "check": corr_doc_check
	}

	val_dob, corr_dob, corr_dob_check = verify_and_correct_checksum(raw_dob, raw_dob_check, is_numeric=True)
	result["checksum_validation"]["date_of_birth"] = {
		"valid": val_dob, "raw": raw_dob, "corrected": corr_dob, "check": corr_dob_check
	}

	val_exp, corr_exp, corr_exp_check = verify_and_correct_checksum(raw_expiry, raw_expiry_check, is_numeric=True)
	result["checksum_validation"]["expiry_date"] = {
		"valid": val_exp, "raw": raw_expiry, "corrected": corr_exp, "check": corr_exp_check
	}

	result["passport_number"] = clean_passport_num
	result["first_name"] = first_name.title() if first_name else "Applicant"
	result["middle_name"] = middle_name.title() if middle_name else None
	result["last_name"] = last_name.title() if last_name else first_name.title()

	parts = [result["first_name"], result["middle_name"], result["last_name"]]
	result["full_name"] = " ".join([p for p in parts if p]).strip()

	nat_country = _resolve_country_name(nationality_code) or ISO_ALPHA3_TO_COUNTRY.get(nationality_code, "Ethiopia")
	result["nationality"] = nat_country

	issue_country = _resolve_country_name(issuing_country_code) or ISO_ALPHA3_TO_COUNTRY.get(issuing_country_code, "Ethiopia")
	result["place_of_issue"] = issue_country

	result["date_of_birth"] = parse_mrz_date(corr_dob, is_expiry=False)
	result["passport_expiry"] = parse_mrz_date(corr_exp, is_expiry=True)
	result["passport_expiry_date"] = result["passport_expiry"]
	result["passport_issue_date"] = infer_passport_issue_date(result["passport_expiry"])

	if sex_char == "F":
		result["gender"] = "Female"
	elif sex_char == "M":
		result["gender"] = "Male"
	else:
		result["gender"] = "Female"

	clean_opt = raw_optional.replace("<", "").strip()
	if clean_opt:
		result["national_id"] = clean_opt

	return result


def parse_mrz_td1(line1, line2, line3):
	"""Parses Type 1 (TD1) ID / Travel Card MRZ (3 lines x 30 characters)."""
	line1 = (line1 + "<" * 30)[:30]
	line2 = (line2 + "<" * 30)[:30]
	line3 = (line3 + "<" * 30)[:30]

	issuing_country_code = line1[2:5].replace("<", "")
	raw_doc_num = line1[5:14]
	raw_doc_check = line1[14]

	raw_dob = line2[0:6]
	raw_dob_check = line2[6]
	sex_char = line2[7].upper()
	raw_expiry = line2[8:14]
	raw_expiry_check = line2[14]
	nationality_code = line2[15:18].replace("<", "")

	name_parts = line3.split("<<")
	surname = name_parts[0].replace("<", " ").strip()
	given_names = name_parts[1].replace("<", " ").strip() if len(name_parts) > 1 else ""
	given_split = given_names.split()
	first_name = given_split[0] if given_split else ""
	middle_name = " ".join(given_split[1:]) if len(given_split) > 1 else ""

	val_doc, corr_doc_num, _ = verify_and_correct_checksum(raw_doc_num, raw_doc_check, is_numeric=False)
	val_dob, corr_dob, _ = verify_and_correct_checksum(raw_dob, raw_dob_check)
	val_exp, corr_exp, _ = verify_and_correct_checksum(raw_expiry, raw_expiry_check)

	gender = "Female" if sex_char == "F" else ("Male" if sex_char == "M" else "Female")
	exp_date = parse_mrz_date(corr_exp, is_expiry=True)

	return {
		"format": "TD1",
		"doc_type": "Identity Card",
		"passport_number": corr_doc_num.replace("<", "").strip(),
		"first_name": first_name.title() or "Applicant",
		"middle_name": middle_name.title() if middle_name else None,
		"last_name": surname.title() if surname else first_name.title(),
		"full_name": f"{first_name} {middle_name} {surname}".replace("  ", " ").strip().title(),
		"nationality": _resolve_country_name(nationality_code) or ISO_ALPHA3_TO_COUNTRY.get(nationality_code, "Ethiopia"),
		"place_of_issue": _resolve_country_name(issuing_country_code) or ISO_ALPHA3_TO_COUNTRY.get(issuing_country_code, "Ethiopia"),
		"date_of_birth": parse_mrz_date(corr_dob, is_expiry=False),
		"passport_expiry": exp_date,
		"passport_expiry_date": exp_date,
		"passport_issue_date": infer_passport_issue_date(exp_date),
		"gender": gender,
	}


def extract_mrz_from_raw_text(raw_text):
	"""Searches OCR text streams for MRZ lines or fallback visual passport data."""
	if not raw_text:
		return None

	raw_lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
	lines = [clean_mrz_line(l) for l in raw_lines]
	lines = [l for l in lines if len(l) >= 20]

	# 1. Look for TD3 lines (starts with P, PQ, PA, PB, etc. or contains <<)
	for i in range(len(lines)):
		l1 = lines[i]
		is_l1_mrz = (
			(l1.startswith("P") and len(l1) >= 28) or
			("<<" in l1 and len(l1) >= 28) or
			("ETH" in l1[:8] and len(l1) >= 28)
		)
		if is_l1_mrz and (i + 1 < len(lines)):
			l2 = lines[i + 1]
			if len(l2) >= 28:
				return parse_mrz_td3(l1, l2)

	# 2. Look for any adjacent lines with << or passport numbers
	for i in range(len(lines) - 1):
		l1 = lines[i]
		l2 = lines[i + 1]
		if (len(l1) >= 30 and len(l2) >= 30) and ("<" in l1 or "<" in l2):
			return parse_mrz_td3(l1, l2)

	# 3. Look for TD1 (3 lines)
	for i in range(len(lines) - 2):
		l1, l2, l3 = lines[i], lines[i + 1], lines[i + 2]
		if 25 <= len(l1) <= 35 and 25 <= len(l2) <= 35 and 25 <= len(l3) <= 35:
			return parse_mrz_td1(l1, l2, l3)

	return extract_visual_passport_data(raw_text)


def _parse_visual_date(date_str):
	"""Parses visual passport dates like '02 DEC 00' or '13 MAY 25' or '12 MAY 2030'."""
	if not date_str:
		return None
	m = re.search(r'([0-9]{1,2})\s*([A-Za-z]{3})\s*([0-9]{2,4})', date_str)
	if m:
		dd = int(m.group(1))
		mon_str = m.group(2).upper()
		yy_str = m.group(3)
		mm = MONTH_MAP.get(mon_str, 1)
		if len(yy_str) == 2:
			yy = int(yy_str)
			curr_yy = datetime.datetime.now().year % 100
			century = 2000 if yy <= curr_yy + 30 else 1900
			full_year = century + yy
		else:
			full_year = int(yy_str)
		return f"{full_year:04d}-{mm:02d}-{dd:02d}"
	return normalize_date_string(date_str)


def normalize_date_string(date_str):
	"""Converts various date formats (DD/MM/YYYY, YYYY-MM-DD, etc.) to ISO YYYY-MM-DD."""
	if not date_str:
		return None
	d = str(date_str).strip()
	m = re.search(r'([0-9]{1,4}[-/.][0-9]{1,2}[-/.][0-9]{1,4})', d)
	if not m:
		return None
	raw = m.group(1).replace("/", "-").replace(".", "-")
	parts = raw.split("-")
	try:
		if len(parts) == 3:
			if len(parts[0]) == 4:
				year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
			else:
				day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
			return str(datetime.date(year, month, day))
	except Exception:
		pass
	try:
		return str(getdate(d))
	except Exception:
		return None


def extract_visual_passport_data(raw_text):
	"""Fallback visual label-based passport field extractor."""
	if not raw_text:
		return None

	lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
	data = {
		"format": "Visual",
		"doc_type": "Passport",
		"passport_number": None,
		"first_name": None,
		"middle_name": None,
		"last_name": None,
		"full_name": None,
		"nationality": "Ethiopia",
		"place_of_issue": "Ethiopia",
		"date_of_birth": None,
		"passport_issue_date": None,
		"passport_expiry": None,
		"passport_expiry_date": None,
		"gender": "Female",
	}

	for i, line in enumerate(lines):
		# Passport number: e.g. Passport No: EQ2576096 or EP1234567
		if re.search(r'(?:Passport\s*No|Passport\s*Number|Doc\s*No)', line, re.I):
			m = re.search(r'\b([A-Z]{1,2}[0-9]{6,9})\b', line)
			if m:
				data["passport_number"] = m.group(1)
			elif i + 1 < len(lines):
				m2 = re.search(r'\b([A-Z]{1,2}[0-9]{6,9})\b', lines[i + 1])
				if m2:
					data["passport_number"] = m2.group(1)

		# Given Names
		if re.search(r'(?:Given\s*Names?|First\s*Name)', line, re.I):
			val = re.sub(r'^(?:Given\s*Names?|First\s*Name)[:=\s]+', '', line, flags=re.I).strip()
			if val and not re.search(r'Passport|Country|Sex|Date', val, re.I):
				parts = val.split()
				if parts:
					data["first_name"] = parts[0].title()
					if len(parts) > 1:
						data["middle_name"] = " ".join(parts[1:]).title()

		# Surname
		if re.search(r'(?:Surname|Last\s*Name)', line, re.I):
			val = re.sub(r'^(?:Surname|Last\s*Name)[:=\s]+', '', line, flags=re.I).strip()
			if val and not re.search(r'Passport|Country|Sex|Date', val, re.I):
				data["last_name"] = val.title()

		# Date of birth
		if re.search(r'(?:Date\s*of\s*birth|DOB|Birth\s*Date)', line, re.I):
			val = re.sub(r'^(?:Date\s*of\s*birth|DOB|Birth\s*Date)[:=\s]+', '', line, flags=re.I).strip()
			parsed_d = _parse_visual_date(val)
			if parsed_d:
				data["date_of_birth"] = parsed_d

		# Expiry date
		if re.search(r'(?:Date\s*of\s*expiry|Expiry\s*Date|Expiration)', line, re.I):
			val = re.sub(r'^(?:Date\s*of\s*expiry|Expiry\s*Date|Expiration)[:=\s]+', '', line, flags=re.I).strip()
			parsed_e = _parse_visual_date(val)
			if parsed_e:
				data["passport_expiry"] = parsed_e
				data["passport_expiry_date"] = parsed_e
				data["passport_issue_date"] = infer_passport_issue_date(parsed_e)

		# Sex / Gender
		if re.search(r'\b(?:Sex|Gender)\b', line, re.I):
			if re.search(r'\b(?:M|Male)\b', line, re.I):
				data["gender"] = "Male"
			elif re.search(r'\b(?:F|Female)\b', line, re.I):
				data["gender"] = "Female"

	if data.get("passport_number") or (data.get("first_name") and data.get("date_of_birth")):
		return data
	return None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Helper Resolution & Pure Mapping
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_country_name(alpha_3: str) -> str | None:
	"""ISO alpha-3 (MRZ) -> Frappe's own Country doctype name."""
	if not alpha_3:
		return None
	clean = alpha_3.strip().upper()
	if clean in ISO_ALPHA3_TO_COUNTRY:
		candidate = ISO_ALPHA3_TO_COUNTRY[clean]
		try:
			if getattr(frappe, "db", None) and frappe.db and frappe.db.exists("Country", candidate):
				return candidate
		except Exception:
			pass
		return candidate

	if pycountry:
		try:
			country = pycountry.countries.get(alpha_3=clean)
			if country:
				try:
					if getattr(frappe, "db", None) and frappe.db:
						name = frappe.db.get_value("Country", {"code": country.alpha_2.lower()}, "name")
						if name:
							return name
				except Exception:
					pass
				return country.name
		except Exception:
			pass

	try:
		if getattr(frappe, "db", None) and frappe.db:
			return frappe.db.get_value("Country", {"name": ["like", f"{clean}%"]}, "name")
	except Exception:
		pass

	return None


def _mrz_date_to_iso(mrz_date: str) -> str | None:
	"""MRZ dates are YYMMDD."""
	return parse_mrz_date(mrz_date, is_expiry=False)


def map_mrz_fields(mrz_dict: dict) -> dict:
	"""Pure mapping from MRZ dictionary to Applicant fieldnames."""
	fields = {}

	doc_num = (mrz_dict.get("number") or mrz_dict.get("passport_number") or "").strip()
	if doc_num:
		fields["passport_number"] = doc_num

	exp_date = mrz_dict.get("passport_expiry_date") or mrz_dict.get("passport_expiry") or _mrz_date_to_iso(mrz_dict.get("expiration_date"))
	if exp_date:
		fields["passport_expiry_date"] = exp_date
		fields["passport_issue_date"] = infer_passport_issue_date(exp_date)

	dob = mrz_dict.get("date_of_birth") or _mrz_date_to_iso(mrz_dict.get("date_of_birth"))
	if dob:
		fields["date_of_birth"] = dob

	sex = (mrz_dict.get("gender") or mrz_dict.get("sex") or "").strip().upper()
	if sex in ("M", "MALE"):
		fields["gender"] = "Male"
	elif sex in ("F", "FEMALE"):
		fields["gender"] = "Female"

	surname = (mrz_dict.get("last_name") or mrz_dict.get("surname") or "").strip().title()
	given_names = (mrz_dict.get("first_name") or mrz_dict.get("names") or "").strip().title()
	if surname and given_names:
		fields["first_name"] = given_names
		fields["last_name"] = surname
	elif given_names:
		fields["first_name"] = given_names

	nat = mrz_dict.get("nationality")
	if not nat:
		nat_alpha3 = (mrz_dict.get("nationality_code") or mrz_dict.get("country") or "").strip().upper()
		nat = _resolve_country_name(nat_alpha3) or ISO_ALPHA3_TO_COUNTRY.get(nat_alpha3)
	if nat:
		fields["nationality"] = nat

	issue_place = mrz_dict.get("place_of_issue")
	if issue_place:
		fields["passport_issue_place"] = issue_place

	return fields


# ─────────────────────────────────────────────────────────────────────────────
# 5. Master Passport MRZ File Parser
# ─────────────────────────────────────────────────────────────────────────────
def parse_passport_mrz(file_path: str) -> dict:
	"""
	Given a filesystem path to a passport scan/photo/PDF, extracts MRZ and returns
	Applicant field updates. Uses multiple parsing strategies:
	1. Text stream extraction (PyMuPDF / pypdf) with ICAO 9303 checksum self-correction
	2. PassportEye MRZ image OCR
	3. Visual regex fallback
	Never raises exceptions — gracefully logs and returns empty dict on failure.
	"""
	from agency_tracking.mock_data import is_mock_parsing_enabled, get_mock_passport_fields
	if is_mock_parsing_enabled():
		return get_mock_passport_fields()

	if not file_path or not os.path.exists(file_path):
		return {}

	# 1. If PDF document, extract text stream directly
	if file_path.lower().endswith(".pdf"):
		try:
			from agency_tracking.contract_parser import extract_text_from_pdf
			raw_text = extract_text_from_pdf(file_path)
			if raw_text:
				parsed = extract_mrz_from_raw_text(raw_text)
				if parsed:
					return map_mrz_fields(parsed)
		except Exception:
			pass

	# 2. Use PassportEye if available
	if read_mrz:
		try:
			mrz = read_mrz(file_path)
			if mrz:
				mrz_dict = mrz.to_dict()
				# If raw lines exist, run through ICAO 9303 checksum validator
				if mrz_dict.get("raw_text"):
					parsed_raw = extract_mrz_from_raw_text(mrz_dict["raw_text"])
					if parsed_raw:
						return map_mrz_fields(parsed_raw)
				return map_mrz_fields(mrz_dict)
		except Exception:
			pass

	# 3. Read image as raw text if pytesseract available
	try:
		import pytesseract
		from PIL import Image
		img = Image.open(file_path)
		ocr_text = pytesseract.image_to_string(img)
		if ocr_text:
			parsed = extract_mrz_from_raw_text(ocr_text)
			if parsed:
				return map_mrz_fields(parsed)
	except Exception:
		pass

	return {}


@frappe.whitelist()
def parse_passport_file(file_url: str) -> dict:
	"""Whitelisted endpoint to parse an uploaded passport scan by file_url or path."""
	file_path = str(file_url)
	if frappe and hasattr(frappe, "db") and frappe.db:
		try:
			file_doc = frappe.db.get_value("File", {"file_url": file_url}, "name")
			if file_doc:
				file_path = frappe.get_doc("File", file_doc).get_full_path()
		except Exception:
			pass
	return parse_passport_mrz(file_path)


