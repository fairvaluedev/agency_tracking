# Copyright (c) 2026, Agency and contributors
# License: MIT. See LICENSE

import random
import string
import datetime

import frappe
from frappe.utils import add_days, add_years

FIRST_NAMES = ['Almaz', 'Betelhem', 'Chaltu', 'Desta', 'Eleni', 'Fatuma', 'Genet', 'Hana', 'Jemila', 'Asnekech']
MIDDLE_NAMES = ['Bekele', 'Girma', 'Haile', 'Kebede', 'Mengistu', 'Tadesse', 'Worku', 'Seid', 'Endris']
LAST_NAMES = ['Alemu', 'Bekele', 'Girma', 'Haile', 'Kebede', 'Mengistu', 'Tadesse', 'Worku', 'Hussen', 'Kemal']
COMPANY_WORDS = ['Al Rashid', 'Al Faisal', 'Al Noor', 'Gulf Star', 'Desert Rose', 'Al Manar', 'Tihamat Asir', 'Al Reef']
KUWAIT_SITES = ['Salmiya, Kuwait City', 'Hawally, Kuwait', 'Farwaniya, Kuwait', 'Jahra, Kuwait']
SAUDI_SITES = ['Riyadh', 'Jeddah', 'Dammam', 'Abha', 'Mecca', 'Medina']


def is_mock_parsing_enabled() -> bool:
	try:
		return bool(frappe.db.get_single_value('Document Parsing Settings', 'use_mock_parsing'))
	except Exception:
		return False


def _rand_digits(n) -> str:
	return ''.join(random.choices(string.digits, k=n))


def _rand_passport_number() -> str:
	letter = random.choice(['EP', 'EQ', 'ER', 'ET'])
	return f'{letter}{_rand_digits(7)}'


def _rand_name() -> str:
	return f'{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}'


def _rand_agency_name(suffix) -> str:
	return f'{random.choice(COMPANY_WORDS)} {suffix} {_rand_digits(3)}'


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


def get_mock_contract_fields(destination_country=None, file_url=None) -> dict:
	if destination_country == 'Kuwait':
		data = {
			'contract_signed_date': _rand_past_date(0, 1),
			'employer_name': _rand_name(),
			'employment_site': random.choice(KUWAIT_SITES),
			'contract_duration': '2 Years',
			'contract_salary_amount': float(random.randint(100, 150)),
			'contract_salary_currency': 'KWD',
			'visa_number': _rand_digits(9),
			'visa_reference_number': _rand_digits(9),
			'visa_type': 'Domestic Worker Visa',
			'sponsor_name': 'فهد حامد حسين المشيعيب',
			'sponsor_civil_id': _rand_digits(9),
			'kuwait_agency_name': 'مكتب مكاتي الريف لاستقدام العمالة المنزلية',
			'kuwait_agency_license': _rand_digits(6),
			'medical_selected_status': 'FIT',
			'medical_2_status': 'FIT',
		}
	else:
		data = {
			'contract_signed_date': _rand_past_date(0, 1),
			'contract_number': f'200{_rand_digits(7)}',
			'visa_number': f'190{_rand_digits(7)}',
			'employer_name': 'ABDULLAH AMER MUGHABBIRI',
			'employer_national_id': f'113{_rand_digits(7)}',
			'employer_address': f'{random.randint(1, 999)} King Fahd Road, Riyadh',
			'saudi_agency_name': 'Tihamat Asir Recruitment company',
			'saudi_agency_license': f'37{_rand_digits(5)}',
			'contract_salary_amount': 1000.0,
			'contract_salary_currency': 'SAR',
			'contract_duration': '2 Years',
			'employment_site': random.choice(SAUDI_SITES),
			'visa_expiry_date': _rand_future_date(1, 3),
			'medical_selected_status': 'FIT',
			'medical_2_status': 'FIT',
		}
	if file_url:
		data['contract_file'] = file_url
	return data


def get_mock_visa_fields(file_url=None) -> dict:
	data = {
		'visa_number': _rand_digits(random.choice([9, 10])),
		'visa_type': random.choice(['Domestic Worker Visa', 'Work Visa']),
		'visa_issue_date': _rand_past_date(0, 1),
		'visa_expiry_date': _rand_future_date(1, 3),
		'visa_reference_number': _rand_digits(9),
		'sponsor_name': 'فهد حامد حسين المشيعيب',
		'sponsor_civil_id': _rand_digits(9),
		'kuwait_agency_name': 'مكتب مكاتي الريف لاستقدام العمالة المنزلية',
		'kuwait_agency_license': _rand_digits(6),
	}
	if file_url:
		data['visa_file'] = file_url
	return data


def get_mock_injaz_fields() -> dict:
	first = random.choice(FIRST_NAMES)
	mid = random.choice(MIDDLE_NAMES)
	last = random.choice(LAST_NAMES)
	return {
		'injaz_number': f'190{_rand_digits(7)}',
		'passport_number': _rand_passport_number(),
		'sponsor_name': 'YOUSEF DABBOUR',
		'origin_agency': 'ANWAR SULTAN FOREIGN EMPLOYMENT AGENT',
		'first_name': first.upper(),
		'middle_name': mid.upper(),
		'last_name': last.upper(),
		'full_name': f'{first} {mid} {last}'.upper(),
		'date_of_birth': _rand_past_date(20, 45),
		'place_of_birth': 'Addis Ababa',
		'nationality': 'Ethiopia',
		'gender': 'Female',
		'religion': 'Muslim',
		'profession': 'Housemaid',
		'passport_issue_date': _rand_past_date(1, 5),
		'passport_expiry_date': _rand_future_date(1, 8),
		'passport_issue_place': 'Addis Ababa',
	}


def get_mock_passport_fields(file_url=None) -> dict:
	first = random.choice(FIRST_NAMES).upper()
	middle = random.choice(MIDDLE_NAMES).upper()
	last = random.choice(LAST_NAMES).upper()
	full = f'{first} {middle} {last}'
	unique_num = _rand_digits(8)

	data = {
		'first_name': first,
		'middle_name': middle,
		'last_name': last,
		'full_name': full,
		'gender': 'Female',
		'nationality': 'Ethiopia',
		'passport_number': _rand_passport_number(),
		'passport_issue_date': _rand_past_date(1, 4),
		'passport_expiry_date': _rand_future_date(2, 7),
		'passport_issue_place': 'Addis Ababa',
		'date_of_birth': _rand_past_date(22, 38),
		'national_id': f'NID-{unique_num}',
		'labor_id': f'LAB-{unique_num}',
		'destination_country': 'Saudi Arabia',
		'salary_amount': 1000.0,
		'salary_currency': 'SAR',
		'religion': 'Muslim',
		'marital_status': 'Single',
		'education': 'High School',
		'target_job': 'Housemaid',
		'emergency_contact_name': f'{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}',
		'emergency_contact_phone': f'+251911{_rand_digits(6)}',
		'phone': f'+251911{_rand_digits(6)}',
		'address': 'Addis Ababa, Bole Sub-City, Woreda 03',
		'medical_status': 'FIT',
		'medical_issue_date': _rand_past_date(0, 1),
		'medical_expiry_date': _rand_future_date(1, 2),
	}

	if file_url:
		data['passport_scan'] = file_url
		data['photograph'] = file_url
		data['photo_full_body'] = file_url

	return data
