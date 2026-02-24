# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Salary data aggregation for Swissdec ELM declarations.

Extracts and aggregates salary data from Salary Slips and related DocTypes
into the format needed by the XML builder and validation engine.
"""

import frappe
from frappe.utils import cint, flt, getdate

from hrms.regional.switzerland.constants import AC_ANNUAL_CEILING, LAA_INSURABLE_SALARY_CAP
from hrms.regional.switzerland.utils import (
	calculate_lpp_coordinated_salary,
	get_employee_age,
	get_swiss_social_insurance_config,
)


def get_employees_for_declaration(company, fiscal_year, declaration_type="Year-End", declaration_month=None):
	"""Get all employees who had submitted salary slips in the period.

	Args:
		company: Company name.
		fiscal_year: Fiscal Year name.
		declaration_type: "Year-End", "Monthly", or "Correction".
		declaration_month: Month number (1-12) for Monthly declarations.

	Returns:
		list of dicts with employee, employee_name, avs_number.
	"""
	fy = frappe.get_doc("Fiscal Year", fiscal_year)

	if declaration_type == "Monthly" and declaration_month:
		year = getdate(fy.year_start_date).year
		period_start, period_end = _get_month_boundaries(year, declaration_month)
	else:
		period_start = fy.year_start_date
		period_end = fy.year_end_date

	employees = frappe.db.sql(
		"""SELECT DISTINCT ss.employee, e.employee_name, e.ch_avs_number
		FROM `tabSalary Slip` ss
		INNER JOIN `tabEmployee` e ON e.name = ss.employee
		WHERE ss.company = %s
			AND ss.start_date >= %s
			AND ss.end_date <= %s
			AND ss.docstatus = 1
		ORDER BY e.employee_name""",
		(company, period_start, period_end),
		as_dict=True,
	)

	return employees


def get_annual_salary_summary(employee, company, year_start, year_end, config=None):
	"""Aggregate all salary components for an employee over the fiscal year.

	Args:
		employee: Employee ID.
		company: Company name.
		year_start: Fiscal year start date.
		year_end: Fiscal year end date.
		config: Optional Swiss Social Insurance Config dict.

	Returns:
		dict with comprehensive salary data for ELM declaration.
	"""
	if not config:
		emp_doc = frappe.get_cached_doc("Employee", employee)
		canton = emp_doc.get("ch_fiscal_canton") or ""
		config = get_swiss_social_insurance_config(company, canton)

	# Get submitted salary slips for the period
	slips = frappe.get_all(
		"Salary Slip",
		filters={
			"employee": employee,
			"company": company,
			"start_date": [">=", year_start],
			"end_date": ["<=", year_end],
			"docstatus": 1,
		},
		fields=["name", "start_date", "end_date", "gross_pay", "net_pay", "total_deduction"],
		order_by="start_date asc",
	)

	if not slips:
		return _empty_salary_summary()

	slip_names = [s.name for s in slips]

	# Get component totals from all slips
	component_totals = _get_component_totals(slip_names)

	# Calculate aggregates
	total_gross = sum(flt(s.gross_pay) for s in slips)
	total_net = sum(flt(s.net_pay) for s in slips)
	months_worked = len(slips)

	# Compute per-insurance-base totals from earnings
	insurance_bases = _get_annual_insurance_base_totals(slip_names)
	avs_salary = insurance_bases.get("avs_base", total_gross)
	ac_base_raw = insurance_bases.get("ac_base", total_gross)
	laa_base_raw = insurance_bases.get("laa_base", total_gross)

	# AC salary = base capped at annual ceiling
	ac_ceiling = flt(config.get("ac_annual_ceiling") if config else 0) or AC_ANNUAL_CEILING
	ac_salary = min(ac_base_raw, ac_ceiling)

	# LAA salary = base capped at insurable salary cap
	laa_cap = flt(config.get("laa_insurable_salary_cap") if config else 0) or LAA_INSURABLE_SALARY_CAP
	laa_salary = min(laa_base_raw, laa_cap)

	# LPP coordinated salary
	emp_doc = frappe.get_cached_doc("Employee", employee)
	age = get_employee_age(employee, year_end)
	lpp_coordinated = calculate_lpp_coordinated_salary(total_gross, config)

	# Source tax total
	source_tax_total = flt(component_totals.get("Source Tax Employee", 0))

	# Social contribution totals
	avs_ee = flt(component_totals.get("AVS/AI/APG Employee", 0))
	avs_er = flt(component_totals.get("AVS/AI/APG Employer", 0))
	ac_ee = flt(component_totals.get("AC/ALV Employee", 0))
	ac_er = flt(component_totals.get("AC/ALV Employer", 0))
	ac_sol_ee = flt(component_totals.get("AC Solidarity Employee", 0))
	ac_sol_er = flt(component_totals.get("AC Solidarity Employer", 0))
	lpp_ee = flt(component_totals.get("LPP/BVG Employee", 0))
	lpp_er = flt(component_totals.get("LPP/BVG Employer", 0))
	laa_prof = flt(component_totals.get("LAA Professional Employer", 0))
	laa_nprof = flt(component_totals.get("LAA Non-Professional Employee", 0))
	ijm_ee = flt(component_totals.get("IJM/KTG Employee", 0))
	ijm_er = flt(component_totals.get("IJM/KTG Employer", 0))
	fak_er = flt(component_totals.get("Family Allowances Employer", 0))

	return {
		"total_gross": round(total_gross, 2),
		"total_net": round(total_net, 2),
		"months_worked": months_worked,
		"component_totals": component_totals,
		"avs_salary": round(avs_salary, 2),
		"ac_salary": round(ac_salary, 2),
		"laa_salary": round(laa_salary, 2),
		"lpp_coordinated": round(lpp_coordinated, 2),
		"source_tax_total": round(source_tax_total, 2),
		"employee_age": age,
		# Contribution details
		"avs_employee": round(avs_ee, 2),
		"avs_employer": round(avs_er, 2),
		"ac_employee": round(ac_ee, 2),
		"ac_employer": round(ac_er, 2),
		"ac_solidarity_employee": round(ac_sol_ee, 2),
		"ac_solidarity_employer": round(ac_sol_er, 2),
		"lpp_employee": round(lpp_ee, 2),
		"lpp_employer": round(lpp_er, 2),
		"laa_professional": round(laa_prof, 2),
		"laa_nonprofessional": round(laa_nprof, 2),
		"ijm_employee": round(ijm_ee, 2),
		"ijm_employer": round(ijm_er, 2),
		"fak_employer": round(fak_er, 2),
		# Period
		"period_start": slips[0].start_date,
		"period_end": slips[-1].end_date,
	}


def get_monthly_salary_summary(employee, company, year, month, config=None):
	"""Aggregate all salary components for an employee for a single month.

	Same return format as get_annual_salary_summary() but scoped to one month.
	AC ceiling is tracked using year-to-date gross from prior months.

	Args:
		employee: Employee ID.
		company: Company name.
		year: Calendar year (int).
		month: Month number (1-12).
		config: Optional Swiss Social Insurance Config dict.

	Returns:
		dict with comprehensive salary data for ELM declaration.
	"""
	if not config:
		emp_doc = frappe.get_cached_doc("Employee", employee)
		canton = emp_doc.get("ch_fiscal_canton") or ""
		config = get_swiss_social_insurance_config(company, canton)

	month_start, month_end = _get_month_boundaries(year, month)

	# Get submitted salary slips for the month
	slips = frappe.get_all(
		"Salary Slip",
		filters={
			"employee": employee,
			"company": company,
			"start_date": [">=", month_start],
			"end_date": ["<=", month_end],
			"docstatus": 1,
		},
		fields=["name", "start_date", "end_date", "gross_pay", "net_pay", "total_deduction"],
		order_by="start_date asc",
	)

	if not slips:
		return _empty_salary_summary()

	slip_names = [s.name for s in slips]

	# Get component totals from month slips
	component_totals = _get_component_totals(slip_names)

	# Calculate monthly aggregates
	total_gross = sum(flt(s.gross_pay) for s in slips)
	total_net = sum(flt(s.net_pay) for s in slips)
	months_worked = 1

	# Compute per-insurance-base totals from earnings
	insurance_bases = _get_annual_insurance_base_totals(slip_names)
	avs_salary = insurance_bases.get("avs_base", total_gross)
	ac_base_raw = insurance_bases.get("ac_base", total_gross)
	laa_base_raw = insurance_bases.get("laa_base", total_gross)

	# AC salary: cap using YTD gross from prior months
	ac_ceiling = flt(config.get("ac_annual_ceiling") if config else 0) or AC_ANNUAL_CEILING
	ytd_gross_before = _get_ytd_gross_before_month(employee, company, year, month)
	if ytd_gross_before >= ac_ceiling:
		# Already above ceiling from prior months
		ac_salary = 0
	elif ytd_gross_before + ac_base_raw > ac_ceiling:
		# Ceiling crossed this month
		ac_salary = ac_ceiling - ytd_gross_before
	else:
		ac_salary = ac_base_raw

	# LAA salary: cap at insurable salary cap (monthly = annual cap / 12)
	laa_cap = flt(config.get("laa_insurable_salary_cap") if config else 0) or LAA_INSURABLE_SALARY_CAP
	laa_monthly_cap = round(laa_cap / 12, 2)
	laa_salary = min(laa_base_raw, laa_monthly_cap)

	# LPP: take contribution amounts directly from slip components
	lpp_ee = flt(component_totals.get("LPP/BVG Employee", 0))
	lpp_er = flt(component_totals.get("LPP/BVG Employer", 0))
	# LPP coordinated salary for the month = annual / 12
	lpp_coordinated = round(calculate_lpp_coordinated_salary(total_gross * 12, config) / 12, 2)

	# Source tax total
	source_tax_total = flt(component_totals.get("Source Tax Employee", 0))

	# Social contribution totals
	avs_ee = flt(component_totals.get("AVS/AI/APG Employee", 0))
	avs_er = flt(component_totals.get("AVS/AI/APG Employer", 0))
	ac_ee = flt(component_totals.get("AC/ALV Employee", 0))
	ac_er = flt(component_totals.get("AC/ALV Employer", 0))
	ac_sol_ee = flt(component_totals.get("AC Solidarity Employee", 0))
	ac_sol_er = flt(component_totals.get("AC Solidarity Employer", 0))
	laa_prof = flt(component_totals.get("LAA Professional Employer", 0))
	laa_nprof = flt(component_totals.get("LAA Non-Professional Employee", 0))
	ijm_ee = flt(component_totals.get("IJM/KTG Employee", 0))
	ijm_er = flt(component_totals.get("IJM/KTG Employer", 0))
	fak_er = flt(component_totals.get("Family Allowances Employer", 0))

	emp_doc = frappe.get_cached_doc("Employee", employee)
	age = get_employee_age(employee, month_end)

	return {
		"total_gross": round(total_gross, 2),
		"total_net": round(total_net, 2),
		"months_worked": months_worked,
		"component_totals": component_totals,
		"avs_salary": round(avs_salary, 2),
		"ac_salary": round(ac_salary, 2),
		"laa_salary": round(laa_salary, 2),
		"lpp_coordinated": round(lpp_coordinated, 2),
		"source_tax_total": round(source_tax_total, 2),
		"employee_age": age,
		# Contribution details
		"avs_employee": round(avs_ee, 2),
		"avs_employer": round(avs_er, 2),
		"ac_employee": round(ac_ee, 2),
		"ac_employer": round(ac_er, 2),
		"ac_solidarity_employee": round(ac_sol_ee, 2),
		"ac_solidarity_employer": round(ac_sol_er, 2),
		"lpp_employee": round(lpp_ee, 2),
		"lpp_employer": round(lpp_er, 2),
		"laa_professional": round(laa_prof, 2),
		"laa_nonprofessional": round(laa_nprof, 2),
		"ijm_employee": round(ijm_ee, 2),
		"ijm_employer": round(ijm_er, 2),
		"fak_employer": round(fak_er, 2),
		# Period
		"period_start": month_start,
		"period_end": month_end,
	}


def get_monthly_salary_details(employee, company, year, month):
	"""Get detailed salary data for a specific month.

	Used for monthly QST declarations.

	Args:
		employee: Employee ID.
		company: Company name.
		year: Calendar year.
		month: Month number (1-12).

	Returns:
		dict with monthly salary details or empty dict.
	"""
	month_start, month_end = _get_month_boundaries(year, month)

	slips = frappe.get_all(
		"Salary Slip",
		filters={
			"employee": employee,
			"company": company,
			"start_date": [">=", month_start],
			"end_date": ["<=", month_end],
			"docstatus": 1,
		},
		fields=["name", "gross_pay", "net_pay"],
	)

	if not slips:
		return {}

	slip_names = [s.name for s in slips]
	component_totals = _get_component_totals(slip_names)
	gross = sum(flt(s.gross_pay) for s in slips)

	return {
		"gross": round(gross, 2),
		"net": round(sum(flt(s.net_pay) for s in slips), 2),
		"source_tax": round(flt(component_totals.get("Source Tax Employee", 0)), 2),
		"component_totals": component_totals,
		"month": month,
		"year": year,
	}


def _get_component_totals(slip_names):
	"""Fetch aggregated component amounts from salary slips.

	Args:
		slip_names: list of Salary Slip names.

	Returns:
		dict mapping component names to total amounts.
	"""
	if not slip_names:
		return {}

	result = {}

	# Earnings
	earnings = frappe.db.sql(
		"""SELECT sd.salary_component, SUM(sd.amount) as total
		FROM `tabSalary Detail` sd
		WHERE sd.parent IN %s AND sd.parentfield = 'earnings'
		GROUP BY sd.salary_component""",
		(slip_names,),
		as_dict=True,
	)
	for row in earnings:
		result[row.salary_component] = round(flt(row.total), 2)

	# Deductions
	deductions = frappe.db.sql(
		"""SELECT sd.salary_component, SUM(sd.amount) as total
		FROM `tabSalary Detail` sd
		WHERE sd.parent IN %s AND sd.parentfield = 'deductions'
		GROUP BY sd.salary_component""",
		(slip_names,),
		as_dict=True,
	)
	for row in deductions:
		result[row.salary_component] = round(flt(row.total), 2)

	return result


def _get_annual_insurance_base_totals(slip_names):
	"""Compute per-insurance-base annual totals from earning components.

	Joins Salary Detail with Salary Component to read the ch_subject_to_* flags
	and sums amounts into per-base totals.

	If no earning has any flag configured (all NULL/0), returns empty dict
	which triggers fallback to total_gross for all bases.
	"""
	if not slip_names:
		return {}

	# Fetch earning amounts with their insurance base flags
	rows = frappe.db.sql(
		"""SELECT sd.salary_component, SUM(sd.amount) as total,
			sc.ch_subject_to_avs, sc.ch_subject_to_ac, sc.ch_subject_to_laa,
			sc.ch_subject_to_ijm, sc.ch_subject_to_lpp, sc.ch_subject_to_imp
		FROM `tabSalary Detail` sd
		LEFT JOIN `tabSalary Component` sc ON sc.name = sd.salary_component
		WHERE sd.parent IN %s AND sd.parentfield = 'earnings'
		GROUP BY sd.salary_component""",
		(slip_names,),
		as_dict=True,
	)

	if not rows:
		return {}

	avs_base = 0
	ac_base = 0
	laa_base = 0
	ijm_base = 0
	lpp_base = 0
	imp_base = 0
	any_flag_set = False

	for row in rows:
		amount = flt(row.total)
		avs = cint(row.ch_subject_to_avs)
		ac = cint(row.ch_subject_to_ac)
		laa = cint(row.ch_subject_to_laa)
		ijm = cint(row.ch_subject_to_ijm)
		lpp = cint(row.ch_subject_to_lpp)
		imp = cint(row.ch_subject_to_imp)

		has_flags = bool(avs or ac or laa or ijm or lpp or imp)
		if has_flags:
			any_flag_set = True

		if has_flags:
			if avs:
				avs_base += amount
			if ac:
				ac_base += amount
			if laa:
				laa_base += amount
			if ijm:
				ijm_base += amount
			if lpp:
				lpp_base += amount
			if imp:
				imp_base += amount
		else:
			# No flags configured — include in all bases (backward compat)
			avs_base += amount
			ac_base += amount
			laa_base += amount
			ijm_base += amount
			lpp_base += amount
			imp_base += amount

	if not any_flag_set:
		return {}

	return {
		"avs_base": round(avs_base, 2),
		"ac_base": round(ac_base, 2),
		"laa_base": round(laa_base, 2),
		"ijm_base": round(ijm_base, 2),
		"lpp_base": round(lpp_base, 2),
		"imp_base": round(imp_base, 2),
	}


def _get_month_boundaries(year, month):
	"""Return the first and last day of the given month as date strings.

	Args:
		year: Calendar year (int).
		month: Month number (1-12).

	Returns:
		tuple of (month_start, month_end) as date strings (YYYY-MM-DD).
	"""
	import calendar

	_, last_day = calendar.monthrange(int(year), int(month))
	month_start = f"{year}-{int(month):02d}-01"
	month_end = f"{year}-{int(month):02d}-{last_day:02d}"
	return month_start, month_end


def _get_ytd_gross_before_month(employee, company, year, month):
	"""Get year-to-date gross salary from January up to (not including) the given month.

	Used for AC ceiling tracking in monthly declarations.

	Args:
		employee: Employee ID.
		company: Company name.
		year: Calendar year.
		month: Month number (1-12). For month=1 returns 0.

	Returns:
		float: Total gross from prior months.
	"""
	if int(month) <= 1:
		return 0

	year_start = f"{year}-01-01"
	month_start = f"{year}-{int(month):02d}-01"

	result = frappe.db.sql(
		"""SELECT COALESCE(SUM(ss.gross_pay), 0) as total
		FROM `tabSalary Slip` ss
		WHERE ss.employee = %s
			AND ss.company = %s
			AND ss.start_date >= %s
			AND ss.start_date < %s
			AND ss.docstatus = 1""",
		(employee, company, year_start, month_start),
		as_dict=True,
	)

	return flt(result[0].total) if result else 0


def _empty_salary_summary():
	"""Return an empty salary summary structure."""
	return {
		"total_gross": 0,
		"total_net": 0,
		"months_worked": 0,
		"component_totals": {},
		"avs_salary": 0,
		"ac_salary": 0,
		"laa_salary": 0,
		"lpp_coordinated": 0,
		"source_tax_total": 0,
		"employee_age": 0,
		"avs_employee": 0,
		"avs_employer": 0,
		"ac_employee": 0,
		"ac_employer": 0,
		"ac_solidarity_employee": 0,
		"ac_solidarity_employer": 0,
		"lpp_employee": 0,
		"lpp_employer": 0,
		"laa_professional": 0,
		"laa_nonprofessional": 0,
		"ijm_employee": 0,
		"ijm_employer": 0,
		"fak_employer": 0,
		"period_start": None,
		"period_end": None,
	}


def get_bvg_projection_data(employee, company, year, base_month=1, has_thirteenth=False, config=None):
	"""Project annual salary for BVG Jahresmeldung.

	Takes the gross salary from a base month and projects it to an annual figure.
	The pension fund uses this to calculate BVG contributions for the coming year.

	Args:
		employee: Employee ID.
		company: Company name.
		year: Calendar year (int).
		base_month: Month to use as projection basis (1-12, default January).
		has_thirteenth: Whether to include 13th month salary (multiply by 13 instead of 12).
		config: Optional Swiss Social Insurance Config dict.

	Returns:
		dict with projected salary data including bvg_projected_salary and lpp_coordinated.
	"""
	if not config:
		emp_doc = frappe.get_cached_doc("Employee", employee)
		canton = emp_doc.get("ch_fiscal_canton") or ""
		config = get_swiss_social_insurance_config(company, canton)

	# Get the base month salary
	month_data = get_monthly_salary_summary(employee, company, year, base_month, config)

	if not month_data or not month_data.get("months_worked"):
		return _empty_salary_summary()

	multiplier = 13 if has_thirteenth else 12
	base_gross = flt(month_data.get("total_gross"))
	projected_annual = base_gross * multiplier

	# Check for employee-level override
	emp_doc = frappe.get_cached_doc("Employee", employee)
	override = flt(emp_doc.get("ch_bvg_basis_override"))
	if override > 0:
		projected_annual = override

	# Calculate LPP coordinated salary from projected annual
	employee_age = get_employee_age(employee, year)
	lpp_coordinated = calculate_lpp_coordinated_salary(projected_annual, config)

	# Build a projection summary (compatible with standard salary data format)
	result = _empty_salary_summary()
	result.update({
		"total_gross": projected_annual,
		"months_worked": multiplier,
		"avs_salary": projected_annual,
		"lpp_coordinated": lpp_coordinated,
		"employee_age": employee_age,
		"bvg_projected_salary": projected_annual,
		"bvg_base_month": base_month,
		"bvg_multiplier": multiplier,
		"bvg_base_month_gross": base_gross,
		"period_start": f"{year}-01-01",
		"period_end": f"{year}-12-31",
	})

	return result
