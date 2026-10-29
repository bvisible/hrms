# //// Neoffice — added file (no upstream equivalent): server side of the Swiss employee wizard
# //// (AVS checksum, source-tax subjection and tariff suggestion, employee creation).
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
from frappe.utils import cint, date_diff, flt, get_year_ending, getdate

from hrms.regional.switzerland.cross_border import suggest_tariff_letter
from hrms.regional.switzerland.permissions import check_company_access
from hrms.regional.switzerland.source_tax import (
	build_tariff_code,
	effective_tariff_code,
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


# The ordinary tariff letter of a personal situation (ESTV): A single, H single living with children
# or other dependants, B married with one income, C married with two. A registered partnership is
# a marriage for the source tax.
def personal_letter(marital_status, spouse_works, children):
	if marital_status == "Married":
		return "C" if cint(spouse_works) else "B"
	return "H" if cint(children) > 0 else "A"


# The same situations for cross-border commuters: the German ones holding the Gre-1 certificate
# (L, M, N, P) and the Italian ones under the 2023 agreement (R, S, T, U).
CROSS_BORDER_LETTERS = {
	"L": {"A": "L", "B": "M", "C": "N", "H": "P"},
	"R": {"A": "R", "B": "S", "C": "T", "H": "U"},
}


def _employee_like(data):
	return frappe._dict(
		ch_is_cross_border=1 if data.get("is_cross_border") else 0,
		ch_residence_country=data.get("residence_country"),
		ch_de_gre1_attestation=1 if data.get("de_gre1") else 0,
		ch_is_italian_new_frontalier=1 if data.get("it_new_frontalier") else 0,
		ch_fr_2041as_attestation=1 if data.get("fr_2041as") else 0,
		ch_cross_border_start_date=data.get("cross_border_start_date"),
	)


def tariff_letter(data):
	"""The tariff letter of the wizard's personal situation, in its cross-border family if any."""
	letter = personal_letter(data.get("marital_status"), data.get("spouse_works"), data.get("num_children"))
	family = suggest_tariff_letter(_employee_like(data)) if data.get("is_cross_border") else None
	return CROSS_BORDER_LETTERS.get(family, {}).get(letter, letter)


def _check_hiring_staff():
	"""Only who may create an Employee hires. check_company_access reads the User Permission
	restrictions, not the roles: a portal customer and an employee without an HR role read the
	company's salary structures and canton through wizard_defaults (three-identity test, 24.09)."""
	if not frappe.has_permission("Employee", "create"):
		frappe.throw(_("Only HR staff can hire an employee."), frappe.PermissionError)


def extend_bootinfo(bootinfo):
	"""Tell the desk whether the Swiss payroll runs on this site: only then does the Employee list's
	"Add" open this wizard (public/js/erpnext/employee_list.js). The whole fleet is Swiss, so a Swiss
	company is not enough — a company with a Swiss Social Insurance Config is."""
	bootinfo.swiss_payroll = bool(
		frappe.db.table_exists("Swiss Social Insurance Config")
		and frappe.db.count("Swiss Social Insurance Config")
	)


@frappe.whitelist()
def wizard_defaults(company):
	"""What the wizard proposes for ``company``: the canton of its payroll, its salary structures,
	its default holiday list and the leave type of the vacation."""
	_check_hiring_staff()
	check_company_access(company)
	from hrms.regional.switzerland.setup import existing_leave_type

	return {
		"canton": frappe.db.get_value(
			"Swiss Social Insurance Config", {"company": company, "is_default": 1}, "canton"
		),
		"structures": frappe.get_all(
			"Salary Structure",
			filters={"company": company, "docstatus": 1, "is_active": "Yes"},
			pluck="name",
			order_by="modified desc",
		),
		"holiday_list": frappe.db.get_value("Company", company, "default_holiday_list"),
		"vacation_leave_type": existing_leave_type("Privilege Leave"),
	}


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
	_check_hiring_staff()
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
	cross_border = qst_subject and data.get("is_cross_border")
	if cross_border:
		suggested_letter = suggest_tariff_letter(_employee_like(data))
	# The wizard gives the personal situation (marital status, spouse's income, children): the letter
	# follows from it; an explicit letter still wins.
	if data.get("marital_status") and qst_subject:
		suggested_letter = tariff_letter(data)
	# The note names the letter the situation ends on (M for a married German commuter with one
	# income), not the first of its cross-border family (L), which contradicted the tariff shown.
	if cross_border and suggested_letter:
		notes.append(_("Cross-border situation suggests tariff letter {0}.").format(suggested_letter))
	if cross_border and data.get("residence_country") == "FR" and data.get("fr_2041as"):
		notes.append(
			_(
				"French cross-border worker with 2041-AS attestation: exempt from Swiss source tax (1983 agreement) in the eligible cantons."
			)
		)
	letter = data.get("tariff_letter") or suggested_letter or "A"
	code = build_tariff_code(letter, data.get("num_children") or 0, data.get("church_tax"))

	# A resident pays the source tax to the canton they live in; a cross-border commuter to the canton
	# where they work.
	if not data.get("is_cross_border") and data.get("residence_canton"):
		canton = data["residence_canton"].upper()
	model = get_calculation_model(canton) if canton else None
	tariff_available = None
	if qst_subject and canton:
		reference = data.get("reference_date") or frappe.utils.today()
		# The code the payroll will use: a canton without church tax at source (GE, NE, TI, VD, VS)
		# publishes only "...N" codes, and the wizard used to announce missing tariffs for a church
		# member there (bench against the certified engine, 2026-09-26).
		effective = effective_tariff_code(canton, code, reference)
		if effective != code:
			notes.append(
				_("Canton {0} levies no church tax at source: tariff {1}.").format(canton, effective)
				if effective.endswith("N")
				else _("Canton {0} levies the church tax at source for everyone: tariff {1}.").format(
					canton, effective
				)
			)
			code = effective
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
	# Before anything is created: the job title is inserted with ignore_permissions.
	_check_hiring_staff()
	if isinstance(data, str):
		data = json.loads(data)
	# //// Neoffice — the company is checked before anything is created: staff limited to company A
	# //// hired into company B, the insert only checking the right on Employee.
	check_company_access(data.get("company"))
	# //// Neoffice — the source tax follows the permit when the caller does not say (art. 83 LIFD),
	# //// as the desk wizard does after its permit step: an API caller hiring a B permit without
	# //// qst_subject created an employee never taxed at source, the employer then liable for the
	# //// tax not withheld (art. 88 LIFD). An explicit 0 or 1 is kept: ordinary taxation (married to
	# //// a Swiss or a C permit holder) is the caller's call.
	if data.get("qst_subject") in (None, ""):
		suggestion = suggest_source_tax(data)
		data["qst_subject"] = 1 if suggestion["qst_subject"] else 0
		if data["qst_subject"] and not data.get("tariff_letter") and suggestion.get("suggested_letter"):
			data["tariff_letter"] = suggestion["suggested_letter"]
	elif cint(data.get("qst_subject")) and not data.get("tariff_letter") and data.get("marital_status"):
		data["tariff_letter"] = tariff_letter(data)

	avs = data.get("avs_number")
	if avs and not is_valid_avs_number(avs):
		frappe.throw(_("Invalid AVS number: the EAN-13 check digit does not match."))
	# The salary account and the address: without them the payment proposal refuses the employee,
	# and the salary certificate prints no address.
	from hrms.regional.switzerland.payment_file import clean_iban, validate_iban

	iban = clean_iban(data.get("iban"))
	if iban and not validate_iban(iban):
		frappe.throw(_("Invalid IBAN: the check digits do not match."))
	address = "\n".join(
		line.strip()
		for line in (data.get("address_street"), data.get("address_town"))
		if (line or "").strip()
	)

	email = (data.get("email") or "").strip()
	designation = (data.get("designation") or "").strip()
	if designation and not frappe.db.exists("Designation", designation):
		frappe.get_doc({"doctype": "Designation", "designation_name": designation}).insert(
			ignore_permissions=True
		)
	work_canton = (data.get("canton") or "").upper()
	# A resident's source tax goes to the canton they live in (art. 107 LIFD); a cross-border
	# commuter's to the canton of the workplace.
	qst_canton = (
		work_canton if data.get("is_cross_border") else (data.get("residence_canton") or work_canton).upper()
	)

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
			"permanent_address": address or None,
			"bank_ac_no": iban or None,
			"salary_mode": "Bank" if iban else None,
			"personal_email": email or None,
			"prefered_contact_email": "Personal Email" if email else None,
			"cell_number": (data.get("mobile") or "").strip() or None,
			"designation": designation or None,
			"marital_status": data.get("marital_status") or None,
			"ch_qst_taxation_canton": qst_canton or None,
			# The payslip reaches the employee by e-mail when there is an address, else by hand.
			"ch_payslip_delivery": "Email" if email else "By Hand",
			# //// Neoffice — the activity at other employers (#839).
			**other_employment_fields(data),
		}
	)
	employee.insert()

	assignment = None
	if not data.get("salary_structure") and flt(data.get("base")):
		# The company's only active structure is the obvious one; with several, the caller chooses.
		structures = frappe.get_all(
			"Salary Structure",
			filters={"company": data.get("company"), "docstatus": 1, "is_active": "Yes"},
			pluck="name",
		)
		if len(structures) == 1:
			data["salary_structure"] = structures[0]
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

	allocation = _allocate_vacation(employee, cint(data.get("vacation_days")))

	frappe.db.commit()
	return {
		"employee": employee.name,
		"employee_name": employee.employee_name,
		"structure_assignment": assignment,
		"leave_allocation": allocation,
	}


def other_employment_fields(data):
	"""The Employee fields of an activity at other employers (#839), asked by the wizard.

	Only for somebody taxed at source: the rate is then set on the whole activity (ESTV Circular 45,
	7.2.1; source_tax.activity_rates). What is known decides which figure is kept."""
	if not cint(data.get("qst_subject")) or not cint(data.get("other_employment")):
		return {"ch_qst_other_employment": 0}
	basis = data.get("other_activity_basis")
	if basis not in ("Unknown", "Work Percentage", "Gross Income"):
		basis = "Unknown"
	return {
		"ch_qst_other_employment": 1,
		"ch_qst_other_activity_basis": basis,
		"ch_qst_other_activity_rate": flt(data.get("other_activity_rate"))
		if basis == "Work Percentage"
		else 0,
		"ch_qst_other_activity_gross": flt(data.get("other_activity_gross"))
		if basis == "Gross Income"
		else 0,
	}


def _allocate_vacation(employee, days_a_year):
	"""The vacation of the year of entry, pro rata of the days left in it (to the half day).

	The balance paid at the exit reads this allocation: an employee hired without one leaves with
	no vacation to pay."""
	if days_a_year <= 0:
		return None
	from hrms.regional.switzerland.setup import existing_leave_type

	leave_type = existing_leave_type("Privilege Leave")
	if not leave_type:
		return None
	start = getdate(employee.date_of_joining)
	end = get_year_ending(start)
	year_days = date_diff(end, start.replace(month=1, day=1)) + 1
	days = round(days_a_year * (date_diff(end, start) + 1) / year_days * 2) / 2
	if days <= 0:
		return None
	allocation = frappe.get_doc(
		{
			"doctype": "Leave Allocation",
			"employee": employee.name,
			"leave_type": leave_type,
			"from_date": start,
			"to_date": end,
			"new_leaves_allocated": days,
			"description": _("{0} days a year, pro rata of the year of entry").format(days_a_year),
		}
	)
	allocation.insert()
	allocation.submit()
	return allocation.name


# //// Neoffice — « finish » mode of the wizard (Jérémy, 29.10.2026). The Neoffice theme gives every desk account an
# //// Employee record that knows a name, a company and a date; the HR staff completes it here, with the same steps and the
# //// same checks as a hire, instead of creating it. The mark « still to complete » is a custom field of the theme
# //// (neo_needs_completion): without it nothing is counted, but any record can still be finished.
# //// Vault note Neoffice/03-DevOps/269.

COMPLETION_FIELD = "neo_needs_completion"
# Read by ema_hooks: completing the record of somebody already in post is not a hire nor a mutation to announce.
ANCHOR_FLAG = "neo_account_employee"


def _completion_ready():
	return frappe.get_meta("Employee").has_field(COMPLETION_FIELD)


def _to_finish():
	"""The Active records still marked, oldest first, among those the caller may read; nothing for who may not write."""
	if not _completion_ready() or not frappe.has_permission("Employee", "write"):
		return []
	return frappe.get_list(
		"Employee",
		filters={COMPLETION_FIELD: 1, "status": "Active"},
		fields=["name", "employee_name"],
		order_by="creation asc, name asc",
		limit_page_length=0,
	)


def _latest_assignment(employee):
	rows = frappe.get_all(
		"Salary Structure Assignment",
		filters={"employee": employee, "docstatus": 1},
		fields=["salary_structure", "base"],
		order_by="from_date desc",
		limit=1,
	)
	return rows[0] if rows else None


def _check_finishing_staff(doc):
	"""Who may write the record finishes it, within the companies they are held to."""
	frappe.has_permission("Employee", "write", doc=doc, throw=True)
	check_company_access(doc.company)


@frappe.whitelist()
def employee_to_finish(employee):
	"""What the assistant knows of a record it is asked to finish: the values to prefill, what is missing and the
	step to start on (a step already complete is skipped)."""
	doc = frappe.get_doc("Employee", employee)
	_check_finishing_staff(doc)
	lines = [line.strip() for line in (doc.permanent_address or "").splitlines() if line.strip()]
	ssa = _latest_assignment(employee)
	nationality = doc.get("ch_nationality") or "Switzerland"
	data = {
		"first_name": doc.first_name,
		"last_name": doc.last_name,
		"gender": doc.gender,
		"date_of_birth": doc.date_of_birth,
		"email": doc.personal_email or doc.company_email or doc.user_id,
		"mobile": doc.cell_number,
		"address_street": lines[0] if lines else None,
		"address_town": lines[1] if len(lines) > 1 else None,
		"avs_number": doc.get("ch_avs_number"),
		"company": doc.company,
		"date_of_joining": doc.date_of_joining,
		"designation": doc.designation,
		"work_percentage": doc.get("ch_work_percentage") or 100,
		"iban": doc.bank_ac_no,
		"holiday_list": doc.holiday_list,
		"base": ssa.base if ssa else None,
		"salary_structure": ssa.salary_structure if ssa else None,
		"nationality": nationality,
		"permit_type": doc.get("ch_permit_type") if nationality != "Switzerland" else None,
		"canton": doc.get("ch_fiscal_canton"),
		"residence_canton": doc.get("ch_qst_taxation_canton"),
		"marital_status": doc.marital_status or "Single",
		"num_children": doc.get("ch_qst_num_children") or 0,
		"church_tax": doc.get("ch_qst_church_tax") or 0,
	}
	data = {key: value for key, value in data.items() if value not in (None, "")}
	person_done = bool(doc.gender and doc.date_of_birth and lines and doc.get("ch_avs_number"))
	job_done = bool(doc.designation and doc.bank_ac_no and ssa)
	return {
		"data": data,
		"known": {"account": doc.user_id, "company": doc.company, "date_of_joining": doc.date_of_joining},
		"first_step": "person" if not person_done else "job" if not job_done else "review",
		"remaining": len(_to_finish()),
	}


@frappe.whitelist()
def next_employee_to_finish(after=None):
	"""The record to finish after ``after`` (the first one without it), or None when none is left."""
	names = [row.name for row in _to_finish()]
	titles = {row.name: row.employee_name for row in _to_finish()}
	rest = [name for name in names if name != after]
	if not rest:
		return None
	if after in names:
		later = names[names.index(after) + 1 :]
		pick = later[0] if later else rest[0]
	else:
		pick = rest[0]
	return {"name": pick, "employee_name": titles.get(pick), "remaining": len(names) - (1 if after in names else 0)}


def _assign_salary(doc, data):
	"""The salary of the record, when it has none yet and the wizard knows one."""
	if not flt(data.get("base")) or frappe.db.exists(
		"Salary Structure Assignment", {"employee": doc.name, "docstatus": 1}
	):
		return None
	structure = data.get("salary_structure")
	if not structure:
		structures = frappe.get_all(
			"Salary Structure",
			filters={"company": doc.company, "docstatus": 1, "is_active": "Yes"},
			pluck="name",
		)
		structure = structures[0] if len(structures) == 1 else None
	if not structure:
		return None
	ssa = frappe.get_doc(
		{
			"doctype": "Salary Structure Assignment",
			"employee": doc.name,
			"salary_structure": structure,
			"company": doc.company,
			"from_date": doc.date_of_joining,
			"base": flt(data.get("base")),
		}
	)
	ssa.insert()
	ssa.submit()
	return ssa.name


@frappe.whitelist()
def complete_employee(employee, data):
	"""Complete the record ``employee`` with the wizard's data and lift its mark.

	Only what the wizard gives is written (a blank never erases what the record holds). Gender and date of birth are
	what the form demands, so they are what finishing demands; the rest can still be missing, and the wizard has said so.
	"""
	if isinstance(data, str):
		data = json.loads(data)
	doc = frappe.get_doc("Employee", employee)
	_check_finishing_staff(doc)
	company = data.get("company") or doc.company
	check_company_access(company)

	if data.get("qst_subject") in (None, ""):
		suggestion = suggest_source_tax(data)
		data["qst_subject"] = 1 if suggestion["qst_subject"] else 0
		if data["qst_subject"] and not data.get("tariff_letter") and suggestion.get("suggested_letter"):
			data["tariff_letter"] = suggestion["suggested_letter"]
	elif cint(data.get("qst_subject")) and not data.get("tariff_letter") and data.get("marital_status"):
		data["tariff_letter"] = tariff_letter(data)

	avs = data.get("avs_number")
	if avs and not is_valid_avs_number(avs):
		frappe.throw(_("Invalid AVS number: the EAN-13 check digit does not match."))
	from hrms.regional.switzerland.payment_file import clean_iban, validate_iban

	iban = clean_iban(data.get("iban"))
	if iban and not validate_iban(iban):
		frappe.throw(_("Invalid IBAN: the check digits do not match."))
	address = "\n".join(
		line.strip() for line in (data.get("address_street"), data.get("address_town")) if (line or "").strip()
	)
	email = (data.get("email") or "").strip()
	designation = (data.get("designation") or "").strip()
	if designation and not frappe.db.exists("Designation", designation):
		frappe.get_doc({"doctype": "Designation", "designation_name": designation}).insert(
			ignore_permissions=True
		)
	work_canton = (data.get("canton") or "").upper()
	qst_canton = (
		work_canton if data.get("is_cross_border") else (data.get("residence_canton") or work_canton).upper()
	)

	values = {
		"first_name": data.get("first_name"),
		"last_name": data.get("last_name"),
		"gender": data.get("gender"),
		"date_of_birth": data.get("date_of_birth"),
		"date_of_joining": data.get("date_of_joining"),
		"company": company,
		"holiday_list": data.get("holiday_list"),
		"ch_avs_number": format_avs_number(avs) if avs else None,
		"ch_nationality": data.get("nationality"),
		"ch_permit_type": data.get("permit_type"),
		"ch_fiscal_canton": work_canton,
		"ch_work_percentage": flt(data.get("work_percentage") or 100),
		"ch_qst_subject": 1 if data.get("qst_subject") else 0,
		"ch_qst_tariff_letter": data.get("tariff_letter"),
		"ch_qst_num_children": int(data.get("num_children") or 0),
		"ch_qst_church_tax": 1 if data.get("church_tax") else 0,
		"ch_is_cross_border": 1 if data.get("is_cross_border") else 0,
		"ch_residence_country": data.get("residence_country"),
		"ch_de_gre1_attestation": 1 if data.get("de_gre1") else 0,
		"ch_fr_2041as_attestation": 1 if data.get("fr_2041as") else 0,
		"ch_is_italian_new_frontalier": 1 if data.get("it_new_frontalier") else 0,
		"ch_cross_border_start_date": data.get("cross_border_start_date"),
		"permanent_address": address,
		"bank_ac_no": iban,
		"salary_mode": "Bank" if iban else None,
		"personal_email": email,
		"prefered_contact_email": "Personal Email" if email else None,
		"cell_number": (data.get("mobile") or "").strip(),
		"designation": designation,
		"marital_status": data.get("marital_status"),
		"ch_qst_taxation_canton": qst_canton,
		"ch_payslip_delivery": "Email" if email else None,
		**other_employment_fields(data),
	}
	doc.update({key: value for key, value in values.items() if value not in (None, "")})

	if not (doc.gender and doc.date_of_birth):
		frappe.throw(_("Gender and date of birth are needed to finish the record."))
	if _completion_ready():
		doc.set(COMPLETION_FIELD, 0)
	doc.flags[ANCHOR_FLAG] = True
	doc.save()

	assignment = _assign_salary(doc, data)
	allocation = None
	if cint(data.get("vacation_days")) > 0 and not frappe.db.exists(
		"Leave Allocation", {"employee": doc.name, "docstatus": 1}
	):
		allocation = _allocate_vacation(doc, cint(data.get("vacation_days")))

	following = next_employee_to_finish(after=doc.name)
	return {
		"employee": doc.name,
		"employee_name": doc.employee_name,
		"structure_assignment": assignment,
		"leave_allocation": allocation,
		"next": following,
		"remaining": following["remaining"] if following else 0,
	}
