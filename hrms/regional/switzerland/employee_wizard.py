# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Swiss employee creation wizard — server side.

Backs the desk page swiss-employee-wizard:

- validate_avs_number: EAN-13 checksum of the 756.XXXX.XXXX.XX number.
- suggest_source_tax: permit/nationality rules -> QST subjection, canton
  model, cross-border treatment and tariff-letter suggestion, plus a
  tariff-data availability check for the resulting code.
- create_employee: create the Employee (and optionally the salary
  structure assignment) from the wizard's collected data.
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import flt, getdate

from hrms.regional.switzerland.cross_border import suggest_tariff_letter
from hrms.regional.switzerland.source_tax import (
	build_tariff_code,
	get_calculation_model,
	tariff_code_exists,
)

# Permits that make an employee subject to source tax (art. 83 LIFD:
# foreign workers without the C settlement permit).
QST_SUBJECT_PERMITS = {
	"Permit B (Residence)",
	"Permit G (Cross-border)",
	"Permit L (Short-term)",
}
QST_EXEMPT_PERMITS = {"Swiss Citizen", "Permit C (Settlement)"}


def is_valid_avs_number(avs):
	"""EAN-13 checksum validation of a Swiss AVS number (756.XXXX.XXXX.XX).

	Accepts dotted or plain 13-digit input. The 13th digit is the EAN-13
	check digit of the first twelve (alternating weights 1 and 3).
	"""
	digits = re.sub(r"\D", "", avs or "")
	if len(digits) != 13 or not digits.startswith("756"):
		return False
	total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:12]))
	return (10 - total % 10) % 10 == int(digits[12])


def format_avs_number(avs):
	"""Normalize to the dotted 756.XXXX.XXXX.XX form."""
	digits = re.sub(r"\D", "", avs or "")
	if len(digits) != 13:
		return avs
	return f"{digits[0:3]}.{digits[3:7]}.{digits[7:11]}.{digits[11:13]}"


@frappe.whitelist()
def validate_avs_number(avs):
	"""Whitelisted AVS checksum validation for the wizard UI."""
	valid = is_valid_avs_number(avs)
	return {"valid": valid, "formatted": format_avs_number(avs) if valid else None}


@frappe.whitelist()
def suggest_source_tax(data):
	"""Derive the source-tax situation from permit / residence data.

	Args:
		data: JSON dict with permit_type, canton, residence_country,
			is_cross_border, de_gre1, it_new_frontalier, tariff_letter,
			num_children, church_tax, reference_date.

	Returns:
		dict with qst_subject, model, suggested_letter, tariff_code,
		tariff_available, notes[].
	"""
	if isinstance(data, str):
		data = json.loads(data)

	permit = data.get("permit_type") or ""
	canton = (data.get("canton") or "").upper()
	notes = []

	qst_subject = permit in QST_SUBJECT_PERMITS
	if permit in QST_EXEMPT_PERMITS:
		notes.append(_("Swiss citizens and C permit holders are taxed ordinarily (no source tax)."))
	elif qst_subject:
		notes.append(_("Foreign workers without a C permit are subject to source tax (art. 83 LIFD)."))

	suggested_letter = None
	if qst_subject and data.get("is_cross_border"):
		employee_like = frappe._dict(
			ch_is_cross_border=1,
			ch_residence_country=data.get("residence_country"),
			ch_de_gre1_attestation=1 if data.get("de_gre1") else 0,
			ch_is_italian_new_frontalier=1 if data.get("it_new_frontalier") else 0,
			ch_fr_2041as_attestation=1 if data.get("fr_2041as") else 0,
			ch_cross_border_start_date=data.get("cross_border_start_date"),
		)
		suggested_letter = suggest_tariff_letter(employee_like)
		if suggested_letter:
			notes.append(
				_("Cross-border situation suggests tariff letter {0}.").format(suggested_letter)
			)
		if data.get("residence_country") == "FR" and data.get("fr_2041as"):
			notes.append(
				_(
					"French cross-border worker with 2041-AS attestation: exempt from Swiss source tax (1983 agreement) in the eligible cantons."
				)
			)

	letter = data.get("tariff_letter") or suggested_letter or "A"
	code = build_tariff_code(letter, data.get("num_children") or 0, data.get("church_tax"))

	model = get_calculation_model(canton) if canton else None
	tariff_available = None
	if qst_subject and canton:
		reference = data.get("reference_date") or frappe.utils.today()
		tariff_available = bool(tariff_code_exists(canton, code, reference))
		if not tariff_available:
			notes.append(
				_("No QST tariff data for {0} {1} — import the year's ESTV files before payroll.").format(
					canton, code
				)
			)

	return {
		"qst_subject": qst_subject,
		"model": model,
		"suggested_letter": suggested_letter,
		"tariff_code": code,
		"tariff_available": tariff_available,
		"notes": notes,
	}


@frappe.whitelist()
def create_employee(data):
	"""Create the Employee (and optional structure assignment) from wizard data.

	Args:
		data: JSON dict — identity (first_name, last_name, gender,
			date_of_birth, avs_number), engagement (company,
			date_of_joining, holiday_list, salary_structure, base),
			status (nationality, permit_type, canton), source tax
			(qst_subject, tariff_letter, num_children, church_tax),
			cross-border (is_cross_border, residence_country, de_gre1,
			fr_2041as, it_new_frontalier, cross_border_start_date).

	Returns:
		dict with employee, employee_name, structure_assignment.
	"""
	if isinstance(data, str):
		data = json.loads(data)

	avs = data.get("avs_number")
	if avs and not is_valid_avs_number(avs):
		frappe.throw(_("Invalid AVS number: the EAN-13 check digit does not match."))

	employee = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": data.get("first_name"),
			"last_name": data.get("last_name"),
			"gender": data.get("gender"),
			"date_of_birth": data.get("date_of_birth"),
			"date_of_joining": data.get("date_of_joining"),
			"company": data.get("company"),
			"status": "Active",
			"holiday_list": data.get("holiday_list") or None,
			"ch_avs_number": format_avs_number(avs) if avs else None,
			"ch_nationality": data.get("nationality") or None,
			"ch_permit_type": data.get("permit_type") or None,
			"ch_fiscal_canton": (data.get("canton") or "").upper() or None,
			"ch_work_percentage": flt(data.get("work_percentage") or 100),
			"ch_qst_subject": 1 if data.get("qst_subject") else 0,
			"ch_qst_tariff_letter": data.get("tariff_letter") or None,
			"ch_qst_num_children": int(data.get("num_children") or 0),
			"ch_qst_church_tax": 1 if data.get("church_tax") else 0,
			"ch_is_cross_border": 1 if data.get("is_cross_border") else 0,
			"ch_residence_country": data.get("residence_country") or None,
			"ch_de_gre1_attestation": 1 if data.get("de_gre1") else 0,
			"ch_fr_2041as_attestation": 1 if data.get("fr_2041as") else 0,
			"ch_is_italian_new_frontalier": 1 if data.get("it_new_frontalier") else 0,
			"ch_cross_border_start_date": data.get("cross_border_start_date") or None,
		}
	)
	employee.insert()

	assignment = None
	if data.get("salary_structure") and flt(data.get("base")):
		ssa = frappe.get_doc(
			{
				"doctype": "Salary Structure Assignment",
				"employee": employee.name,
				"salary_structure": data.get("salary_structure"),
				"company": data.get("company"),
				"from_date": data.get("date_of_joining"),
				"base": flt(data.get("base")),
			}
		)
		ssa.insert()
		ssa.submit()
		assignment = ssa.name

	frappe.db.commit()
	return {
		"employee": employee.name,
		"employee_name": employee.employee_name,
		"structure_assignment": assignment,
	}
