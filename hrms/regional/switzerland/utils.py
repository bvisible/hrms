# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from hrms.regional.switzerland.constants import (
	AC_ANNUAL_CEILING,
	AC_RATE_EMPLOYEE,
	AC_RATE_EMPLOYER,
	AC_SOLIDARITY_RATE_EMPLOYEE,
	AC_SOLIDARITY_RATE_EMPLOYER,
	AVS_RATE_EMPLOYEE,
	AVS_RATE_EMPLOYER,
	LPP_AGE_BRACKETS,
	LPP_COORDINATION_DEDUCTION,
	LPP_ENTRY_THRESHOLD,
	LPP_MAXIMUM_COORDINATED_SALARY,
	LPP_MINIMUM_INSURED_SALARY,
	RATE_BASED_COMPONENTS,
)


def get_swiss_social_insurance_config(company, canton=None):
	"""Fetch the Swiss Social Insurance Config for a company/canton pair.

	If canton is provided, look for a canton-specific config first.
	Falls back to the default config for the company.
	"""
	if canton:
		# Try canton-specific config first
		config = frappe.db.get_value(
			"Swiss Social Insurance Config",
			{"company": company, "canton": canton},
			"*",
			as_dict=True,
		)
		if config:
			return config

	# Fall back to default config
	config = frappe.db.get_value(
		"Swiss Social Insurance Config",
		{"company": company, "is_default": 1},
		"*",
		as_dict=True,
	)
	return config


def get_lpp_rate_for_age(age):
	"""Return the LPP/BVG contribution rate based on employee age.

	Returns the total rate (employee + employer combined).
	Below age 25 or above 65, returns 0 (not insured under BVG minimum).
	"""
	for bracket in LPP_AGE_BRACKETS:
		if bracket["min_age"] <= age <= bracket["max_age"]:
			return bracket["rate"]
	return 0


def calculate_lpp_coordinated_salary(annual_salary, config=None):
	"""Calculate the LPP/BVG coordinated (insured) salary.

	Applies the coordination deduction and enforces minimum/maximum thresholds.

	Args:
		annual_salary: Gross annual salary in CHF
		config: Optional SwissSocialInsuranceConfig dict with custom thresholds

	Returns:
		The annual coordinated salary (amount on which LPP contributions are calculated)
	"""
	entry_threshold = flt(config.get("lpp_entry_threshold") if config else 0) or LPP_ENTRY_THRESHOLD
	coordination_deduction = (
		flt(config.get("lpp_coordination_deduction") if config else 0) or LPP_COORDINATION_DEDUCTION
	)
	minimum_insured = (
		flt(config.get("lpp_minimum_insured_salary") if config else 0) or LPP_MINIMUM_INSURED_SALARY
	)
	maximum_coordinated = (
		flt(config.get("lpp_maximum_coordinated_salary") if config else 0) or LPP_MAXIMUM_COORDINATED_SALARY
	)

	annual_salary = flt(annual_salary)

	# Below entry threshold: not insured
	if annual_salary < entry_threshold:
		return 0

	# Calculate coordinated salary
	coordinated = annual_salary - coordination_deduction

	# Apply minimum insured salary
	if coordinated < minimum_insured:
		coordinated = minimum_insured

	# Apply maximum
	if coordinated > maximum_coordinated:
		coordinated = maximum_coordinated

	return coordinated


def calculate_lpp_contribution(annual_salary, age, config=None):
	"""Calculate monthly LPP/BVG contribution amounts for employee and employer.

	Args:
		annual_salary: Gross annual salary in CHF
		age: Employee age in years
		config: Optional SwissSocialInsuranceConfig dict

	Returns:
		dict with keys: coordinated_salary, total_rate, total_annual,
		employee_monthly, employer_monthly
	"""
	coordinated_salary = calculate_lpp_coordinated_salary(annual_salary, config)
	total_rate = get_lpp_rate_for_age(age)

	if not coordinated_salary or not total_rate:
		return {
			"coordinated_salary": 0,
			"total_rate": 0,
			"total_annual": 0,
			"employee_monthly": 0,
			"employer_monthly": 0,
		}

	employer_share_pct = flt(config.get("lpp_employer_share_pct") if config else 0) / 100 or 0.5
	employer_share_pct = max(employer_share_pct, 0.5)  # Minimum 50% by law

	total_annual = coordinated_salary * total_rate
	employer_annual = total_annual * employer_share_pct
	employee_annual = total_annual - employer_annual

	return {
		"coordinated_salary": coordinated_salary,
		"total_rate": total_rate,
		"total_annual": total_annual,
		"employee_monthly": round(employee_annual / 12, 2),
		"employer_monthly": round(employer_annual / 12, 2),
	}


def calculate_ac_contribution(monthly_gross, ytd_gross, config=None):
	"""Calculate AC/ALV contribution for a given month, respecting annual ceiling.

	Handles the transition from standard rate to solidarity rate when the
	annual ceiling is reached mid-year.

	Args:
		monthly_gross: Gross salary for the current month
		ytd_gross: Year-to-date gross salary BEFORE the current month
		config: Optional SwissSocialInsuranceConfig dict

	Returns:
		dict with keys: ac_employee, ac_employer, solidarity_employee, solidarity_employer,
		subject_to_ac, subject_to_solidarity
	"""
	ceiling = flt(config.get("ac_annual_ceiling") if config else 0) or AC_ANNUAL_CEILING
	ac_rate_ee = flt(config.get("ac_rate_employee") if config else 0) / 100 or AC_RATE_EMPLOYEE
	ac_rate_er = flt(config.get("ac_rate_employer") if config else 0) / 100 or AC_RATE_EMPLOYER
	sol_rate_ee = (
		flt(config.get("ac_solidarity_rate_employee") if config else 0) / 100 or AC_SOLIDARITY_RATE_EMPLOYEE
	)
	sol_rate_er = (
		flt(config.get("ac_solidarity_rate_employer") if config else 0) / 100 or AC_SOLIDARITY_RATE_EMPLOYER
	)

	monthly_gross = flt(monthly_gross)
	ytd_gross = flt(ytd_gross)
	new_ytd = ytd_gross + monthly_gross

	# Determine how much of this month's salary is below vs above ceiling
	if ytd_gross >= ceiling:
		# Already above ceiling: entire salary subject to solidarity only
		subject_to_ac = 0
		subject_to_solidarity = monthly_gross
	elif new_ytd <= ceiling:
		# Still below ceiling: entire salary subject to standard AC
		subject_to_ac = monthly_gross
		subject_to_solidarity = 0
	else:
		# Ceiling crossed this month: split
		subject_to_ac = ceiling - ytd_gross
		subject_to_solidarity = monthly_gross - subject_to_ac

	return {
		"ac_employee": round(subject_to_ac * ac_rate_ee, 2),
		"ac_employer": round(subject_to_ac * ac_rate_er, 2),
		"solidarity_employee": round(subject_to_solidarity * sol_rate_ee, 2),
		"solidarity_employer": round(subject_to_solidarity * sol_rate_er, 2),
		"subject_to_ac": subject_to_ac,
		"subject_to_solidarity": subject_to_solidarity,
	}


def get_employee_age(employee, reference_date=None):
	"""Calculate employee age from date of birth.

	Args:
		employee: Employee name or dict with date_of_birth field
		reference_date: Date to calculate age at (defaults to today)

	Returns:
		Age in years (integer)
	"""
	if isinstance(employee, str):
		date_of_birth = frappe.db.get_value("Employee", employee, "date_of_birth")
	else:
		date_of_birth = employee.get("date_of_birth")

	if not date_of_birth:
		return 0

	reference_date = getdate(reference_date) if reference_date else getdate(today())
	date_of_birth = getdate(date_of_birth)

	age = reference_date.year - date_of_birth.year
	if (reference_date.month, reference_date.day) < (date_of_birth.month, date_of_birth.day):
		age -= 1

	return age


def get_ytd_gross_for_employee(employee, company, start_date, end_date):
	"""Get year-to-date gross salary for an employee, excluding the current period.

	Used for AC ceiling tracking.

	Args:
		employee: Employee ID
		company: Company name
		start_date: Start date of the current payroll period
		end_date: End date of the current payroll period

	Returns:
		YTD gross salary in CHF (float)
	"""
	# Determine fiscal year start
	year_start = getdate(start_date).replace(month=1, day=1)

	result = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(ss.gross_pay), 0) as ytd_gross
		FROM `tabSalary Slip` ss
		WHERE ss.employee = %s
			AND ss.company = %s
			AND ss.start_date >= %s
			AND ss.end_date < %s
			AND ss.docstatus = 1
		""",
		(employee, company, year_start, start_date),
		as_dict=True,
	)

	return flt(result[0].ytd_gross) if result else 0


def calculate_thirteenth_month(base_monthly, employee, slip_start, slip_end, config):
	"""Calculate 13th month salary amount for a salary slip.

	Args:
		base_monthly: Base monthly salary (Basic component amount)
		employee: Employee name (string) or dict/doc with date_of_joining, relieving_date
		slip_start: Salary slip start date
		slip_end: Salary slip end date
		config: Swiss Social Insurance Config dict

	Returns:
		13th month amount for this salary slip (float)
	"""
	mode = (config.get("thirteenth_month_mode") or "Disabled") if config else "Disabled"
	base_monthly = flt(base_monthly)

	if mode == "Disabled" or not base_monthly:
		return 0

	if mode == "Monthly":
		return round(base_monthly / 12, 2)

	# Annual mode: pay only in December or on the relieving month
	slip_end_date = getdate(slip_end)
	is_december = slip_end_date.month == 12

	# Get employee data
	if isinstance(employee, str):
		emp_doc = frappe.get_cached_doc("Employee", employee)
	else:
		emp_doc = employee

	relieving_date = emp_doc.get("relieving_date")
	is_relieving_month = (
		relieving_date
		and getdate(relieving_date).month == slip_end_date.month
		and getdate(relieving_date).year == slip_end_date.year
	)

	if not is_december and not is_relieving_month:
		return 0

	# Calculate pro-rata based on days worked in the year
	year_start = slip_end_date.replace(month=1, day=1)
	year_end = slip_end_date.replace(month=12, day=31)

	date_of_joining = getdate(emp_doc.get("date_of_joining"))
	period_start = max(date_of_joining, year_start)

	if relieving_date:
		period_end = min(getdate(relieving_date), year_end)
	else:
		period_end = year_end

	if period_start > period_end:
		return 0

	total_days_in_year = (year_end - year_start).days + 1
	days_worked = (period_end - period_start).days + 1
	pro_rata = days_worked / total_days_in_year

	return round(base_monthly * pro_rata, 2)


def get_component_rates_for_salary_slip(doc):
	"""Return a dict of {component_name: rate_display_string} for a salary slip.

	Used by the Swiss pay slip print format to display contribution rates
	next to each deduction component.

	Args:
		doc: Salary Slip document

	Returns:
		dict mapping component names to rate strings (e.g., "5.3", "7.0")
	"""
	employee = frappe.get_cached_doc("Employee", doc.employee)
	canton = employee.get("ch_fiscal_canton") or ""
	config = get_swiss_social_insurance_config(doc.company, canton)

	if not config:
		return {}

	age = get_employee_age(doc.employee, doc.end_date)
	return _build_rate_dict(config, age)


def _build_rate_dict(config, age):
	"""Build a dict of component rates from config and employee age.

	Pure function (no frappe dependency) for testability.

	Args:
		config: Swiss Social Insurance Config dict
		age: Employee age in years

	Returns:
		dict mapping component names to rate strings
	"""
	rates = {}

	# Rate-based components: direct rate from config
	for comp_name, (rate_field, _is_employer, _base_type) in RATE_BASED_COMPONENTS.items():
		rate = flt(config.get(rate_field))
		if rate:
			rates[comp_name] = str(rate)

	# AC/ALV: standard rate from config
	ac_rate_ee = flt(config.get("ac_rate_employee"))
	ac_rate_er = flt(config.get("ac_rate_employer"))
	if ac_rate_ee:
		rates["AC/ALV Employee"] = str(ac_rate_ee)
	if ac_rate_er:
		rates["AC/ALV Employer"] = str(ac_rate_er)

	# AC Solidarity
	sol_rate_ee = flt(config.get("ac_solidarity_rate_employee"))
	sol_rate_er = flt(config.get("ac_solidarity_rate_employer"))
	if sol_rate_ee:
		rates["AC Solidarity Employee"] = str(sol_rate_ee)
	if sol_rate_er:
		rates["AC Solidarity Employer"] = str(sol_rate_er)

	# LPP/BVG: age-based rate (total rate, then split)
	lpp_total_rate = get_lpp_rate_for_age(age)
	if lpp_total_rate:
		raw_share = float(config.get("lpp_employer_share_pct") or 0) / 100 or 0.5
		employer_share = max(raw_share, 0.5)
		employee_rate = round(lpp_total_rate * (1 - employer_share) * 100, 2)
		employer_rate = round(lpp_total_rate * employer_share * 100, 2)
		if employee_rate:
			rates["LPP/BVG Employee"] = str(employee_rate)
		if employer_rate:
			rates["LPP/BVG Employer"] = str(employer_rate)

	return rates


def format_chf(value, show_zero=False):
	"""Format a number with Swiss apostrophe thousands separator.

	Examples: 12345.60 -> "12'345.60", 0 -> ""
	"""
	if not value and not show_zero:
		return ""
	value = flt(value, 2)
	formatted = f"{abs(value):,.2f}".replace(",", "'")
	if value < 0:
		formatted = "-" + formatted
	return formatted


def get_salary_slip_print_data(doc):
	"""Prepare enriched data for the Swiss salary slip print format.

	Pre-computes all data needed by the template so it doesn't need
	to call frappe.get_cached_doc() in Jinja loops.
	"""
	employee = frappe.get_cached_doc("Employee", doc.employee)
	config = get_swiss_social_insurance_config(
		doc.company, employee.get("ch_fiscal_canton") or ""
	)
	age = get_employee_age(doc.employee, doc.end_date)
	rates = _build_rate_dict(config, age) if config else {}

	# Salutation
	gender = (employee.get("gender") or "").strip()
	if gender == "Female":
		salutation = "Madame"
	elif gender == "Male":
		salutation = "Monsieur"
	else:
		salutation = ""

	# Employee address
	address_lines = _parse_address(employee)

	# Company address
	company_doc = frappe.get_cached_doc("Company", doc.company)
	company_address = _parse_company_address(company_doc)

	# Employer component names (set for fast lookup)
	employer_set = set(
		frappe.get_all(
			"Salary Component",
			filters={"is_employer_contribution": 1},
			pluck="name",
		)
	)

	# Build enriched earnings
	earnings = []
	insurance_bases = {
		"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0, "gross": 0
	}
	any_flag = False

	comp_fields = [
		"ch_wage_type_code", "ch_subject_to_avs", "ch_subject_to_ac",
		"ch_subject_to_laa", "ch_subject_to_ijm", "ch_subject_to_lpp", "ch_subject_to_imp",
	]

	for row in doc.get("earnings", []):
		comp_vals = frappe.get_cached_value(
			"Salary Component", row.salary_component, comp_fields, as_dict=True
		) or {}
		gs_code = comp_vals.get("ch_wage_type_code") or ""
		earnings.append({
			"gs_code": gs_code,
			"name": row.salary_component,
			"amount": flt(row.amount, 2),
		})

		# Accumulate insurance bases
		amount = flt(row.default_amount or row.amount, 2)
		insurance_bases["gross"] += amount

		flags = {
			"avs": comp_vals.get("ch_subject_to_avs"),
			"ac": comp_vals.get("ch_subject_to_ac"),
			"laa": comp_vals.get("ch_subject_to_laa"),
			"ijm": comp_vals.get("ch_subject_to_ijm"),
			"lpp": comp_vals.get("ch_subject_to_lpp"),
			"imp": comp_vals.get("ch_subject_to_imp"),
		}
		if any(flags.values()):
			any_flag = True
			for key in ("avs", "ac", "laa", "ijm", "lpp", "imp"):
				if flags[key]:
					insurance_bases[key] += amount

	# Backward compat: if no flags configured, all bases = gross
	if not any_flag:
		for key in ("avs", "ac", "laa", "ijm", "lpp", "imp"):
			insurance_bases[key] = insurance_bases["gross"]

	# Build enriched deductions (employee and employer separate)
	deductions_ee = []
	deductions_er = []
	total_ee = 0
	total_er = 0

	for row in doc.get("deductions", []):
		if not flt(row.amount):
			continue
		comp_name = row.salary_component
		is_employer = comp_name in employer_set
		comp_vals = frappe.get_cached_value(
			"Salary Component", comp_name, ["ch_wage_type_code"], as_dict=True
		) or {}
		gs_code = comp_vals.get("ch_wage_type_code") or ""

		rate_str = rates.get(comp_name, "")
		determinant = _compute_determinant(comp_name, flt(row.amount, 2), rate_str, insurance_bases)

		entry = {
			"gs_code": gs_code,
			"name": comp_name,
			"determinant": flt(determinant, 2),
			"rate": rate_str,
			"amount": flt(row.amount, 2),
		}

		if is_employer:
			deductions_er.append(entry)
			total_er += flt(row.amount, 2)
		else:
			deductions_ee.append(entry)
			total_ee += flt(row.amount, 2)

	# Period label
	try:
		end = getdate(doc.end_date)
		months_fr = [
			"", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
			"Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
		]
		period_label = f"{months_fr[end.month]} {end.year}"
	except Exception:
		period_label = ""

	return {
		"employee": employee,
		"salutation": salutation,
		"address_lines": address_lines,
		"company_address": company_address,
		"period_label": period_label,
		"earnings": earnings,
		"deductions_ee": deductions_ee,
		"deductions_er": deductions_er,
		"insurance_bases": insurance_bases,
		"totals": {
			"gross": flt(doc.gross_pay, 2),
			"ee_deductions": flt(total_ee, 2),
			"net": flt(doc.net_pay, 2),
			"rounded": flt(doc.rounded_total, 2) if doc.rounded_total else 0,
			"er_contributions": flt(total_er, 2),
			"employer_cost": flt(doc.gross_pay, 2) + flt(total_er, 2),
		},
		"total_in_words": doc.total_in_words or "",
	}


def _compute_determinant(comp_name, amount, rate_str, insurance_bases):
	"""Compute the determinant (base amount) for a deduction component."""
	# Check RATE_BASED_COMPONENTS first for direct base type mapping
	if comp_name in RATE_BASED_COMPONENTS:
		_, _, base_type = RATE_BASED_COMPONENTS[comp_name]
		return insurance_bases.get(base_type.replace("_base", ""), 0)

	# AC/ALV: use ac base or back-calculate if capped
	if "AC/ALV" in comp_name or "AC Solidarity" in comp_name:
		rate = flt(rate_str)
		if rate and amount:
			return round(abs(amount) / (rate / 100), 2)
		return insurance_bases.get("ac", 0)

	# LPP/BVG: back-calculate from amount and rate (coordinated salary)
	if "LPP/BVG" in comp_name:
		rate = flt(rate_str)
		if rate and amount:
			return round(abs(amount) / (rate / 100), 2)
		return 0

	# Source Tax: use imp_base
	if "Source Tax" in comp_name:
		return insurance_bases.get("imp", 0)

	# Default: no determinant
	return 0


def _parse_address(employee):
	"""Parse employee address into lines for the print format."""
	lines = []
	addr = employee.get("current_address") or employee.get("permanent_address") or ""
	if addr:
		# Address is stored as a small text with newlines
		for line in addr.strip().split("\n"):
			line = line.strip()
			if line:
				lines.append(line)
	return lines


def _parse_company_address(company_doc):
	"""Parse company address into lines for the print format."""
	lines = []
	# Try company address fields
	for field in ("address_line1", "address_line2", "city", "pincode"):
		val = company_doc.get(field)
		if val:
			lines.append(str(val).strip())

	if not lines:
		# Fallback: try to get from Address doctype
		address_name = frappe.db.get_value(
			"Dynamic Link",
			{"link_doctype": "Company", "link_name": company_doc.name, "parenttype": "Address"},
			"parent",
		)
		if address_name:
			addr = frappe.get_cached_doc("Address", address_name)
			for field in ("address_line1", "address_line2"):
				val = addr.get(field)
				if val:
					lines.append(str(val).strip())
			city_line = ""
			if addr.get("pincode"):
				city_line += str(addr.pincode)
			if addr.get("city"):
				city_line += " " + str(addr.city) if city_line else str(addr.city)
			if city_line:
				lines.append(city_line.strip())
	return lines
