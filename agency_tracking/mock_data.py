# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE
#
# Fixture data for contract/visa/injaz/passport parsing, returned instead of running
# real PDF/OCR extraction when Document Parsing Settings.use_mock_parsing is on.
# Values are randomized on every call — several downstream fields (passport_number,
# national_id, labor_id) are globally unique on Applicant, so fixed constants would
# collide across repeated test/dev uploads.

import random
import string
import datetime

import frappe
from frappe.utils import add_days, add_years

FIRST_NAMES = ["Almaz", "Betelhem", "Chaltu", "Desta", "Eleni", "Fatuma", "Genet", "Hana"]
LAST_NAMES = ["Alemu", "Bekele", "Girma", "Haile", "Kebede", "Mengistu", "Tadesse", "Worku"]
COMPANY_WORDS = ["Al Rashid", "Al Faisal", "Al Noor", "Gulf Star", "Desert Rose", "Al Manar"]
KUWAIT_SITES = ["Salmiya, Kuwait City", "Hawally, Kuwait", "Farwaniya, Kuwait", "Jahra, Kuwait"]


def is_mock_parsing_enabled() -> bool:
	try:
		return bool(frappe.db.get_single_value("Document Parsing Settings", "use_mock_parsing"))
	except Exception:
		return False


def _rand_digits(n) -> str:
	return "".join(random.choices(string.digits, k=n))


def _rand_passport_number() -> str:
	letters = "".join(random.choices(string.ascii_uppercase, k=random.choice([1, 2])))
	return f"{letters}{_rand_digits(7)}"


def _rand_name() -> str:
	return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def _rand_agency_name(suffix) -> str:
	return f"{random.choice(COMPANY_WORDS)} {suffix} {_rand_digits(3)}"


def _rand_past_date(min_years_ago, max_years_ago) -> str:
	min_days = int(min_years_ago * 365)
	max_days = int(max_years_ago * 365)
	days_ago = random.randint(min_days, max_days) if max_days > min_days else min_days
	return str(add_days(datetime.date.today(), -days_ago))


def _rand_future_date(min_years, max_years) -> str:
	min_days = int(min_years * 365)
	max_days = int(max_years * 365)
	days_ahead = random.randint(min_days, max_days) if max_days > min_days else min_days
	return str(add_days(datetime.date.today(), days_ahead))


def get_mock_contract_fields(destination_country=None) -> dict:
	if destination_country == "Kuwait":
		return {
			"contract_signed_date": _rand_past_date(0, 1),
			"employer_name": _rand_name(),
			"employment_site": random.choice(KUWAIT_SITES),
			"contract_duration": "2 Years",
			"contract_salary_amount": float(random.randint(90, 180)),
			"contract_salary_currency": "KWD",
		}

	return {
		"contract_signed_date": _rand_past_date(0, 1),
		"contract_number": f"MOCK-CN-{_rand_digits(6)}",
		"visa_number": _rand_digits(10),
		"employer_name": _rand_name(),
		"employer_national_id": _rand_digits(10),
		"employer_address": f"{random.randint(1, 999)} Mock Street, Riyadh",
		"saudi_agency_name": _rand_agency_name("Recruiting Agency"),
		"saudi_agency_license": f"SA-LIC-{_rand_digits(6)}",
		"contract_salary_amount": float(random.randint(1200, 2200)),
		"contract_salary_currency": "SAR",
		"visa_expiry_date": _rand_future_date(1, 3),
	}


def get_mock_visa_fields() -> dict:
	return {
		"visa_number": _rand_digits(random.choice([9, 10])),
		"visa_type": random.choice(["Domestic Worker Visa", "Work Visa"]),
		"visa_issue_date": _rand_past_date(0, 1),
		"visa_expiry_date": _rand_future_date(1, 3),
		"visa_reference_number": _rand_digits(9),
		"sponsor_name": _rand_name(),
		"sponsor_civil_id": _rand_digits(9),
		"kuwait_agency_name": _rand_agency_name("Recruitment Office"),
		"kuwait_agency_license": _rand_digits(6),
	}


def get_mock_injaz_fields() -> dict:
	return {
		"injaz_number": _rand_digits(10),
		"passport_number": _rand_passport_number(),
		"sponsor_name": _rand_name(),
		"origin_agency": f"{random.choice(COMPANY_WORDS)} EMPLOYMENT AGENT",
		"full_name": _rand_name(),
		"date_of_birth": _rand_past_date(20, 45),
		"place_of_birth": "Addis Ababa",
		"nationality": "Ethiopia",
		"gender": random.choice(["Female", "Male"]),
		"religion": random.choice(["Muslim", "Orthodox", "Protestant", "Catholic"]),
		"profession": "Domestic Worker",
		"passport_issue_date": _rand_past_date(1, 5),
		"passport_expiry_date": _rand_future_date(1, 8),
		"passport_issue_place": "Ethiopia",
	}


def get_mock_passport_fields() -> dict:
	first, last = _rand_name().split(" ", 1)
	return {
		"passport_number": _rand_passport_number(),
		"first_name": first,
		"middle_name": random.choice(LAST_NAMES),
		"last_name": last,
		"date_of_birth": _rand_past_date(20, 45),
		"passport_issue_date": _rand_past_date(1, 5),
		"passport_expiry_date": _rand_future_date(1, 8),
		"gender": random.choice(["Female", "Male"]),
		"nationality": "Ethiopia",
		"passport_issue_place": "Ethiopia",
	}
