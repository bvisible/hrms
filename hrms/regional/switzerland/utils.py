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
		"employee_monthly": flt(employee_annual / 12, 2),
		"employer_monthly": flt(employer_annual / 12, 2),
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
		"ac_employee": flt(subject_to_ac * ac_rate_ee, 2),
		"ac_employer": flt(subject_to_ac * ac_rate_er, 2),
		"solidarity_employee": flt(subject_to_solidarity * sol_rate_ee, 2),
		"solidarity_employer": flt(subject_to_solidarity * sol_rate_er, 2),
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
