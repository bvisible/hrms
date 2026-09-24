# //// Neoffice — added file (no upstream equivalent): the Swiss contribution helpers themselves
# //// (AVS/AC/LAA/IJM/LPP, 13th month, commercial rounding) plus the jinja helpers the
# //// Swiss print formats call.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import re

import frappe
from frappe import _

# //// Neoffice — formatdate added: the payslip period label now goes through the framework's
# //// date formatting instead of a hardcoded French month list (issue #239)
from frappe.utils import add_months, cint, flt, formatdate, getdate, today

# //// Neoffice — AC and LPP contributions round to 5 centimes (Swissdec guidelines 4.1.1).
from hrms.regional.switzerland.ceilings import month_insured
from hrms.regional.switzerland.constants import (
	AC_ANNUAL_CEILING,
	AC_RATE_EMPLOYEE,
	AC_RATE_EMPLOYER,
	AVS_RATE_EMPLOYEE,
	AVS_RATE_EMPLOYER,
	LPP_AGE_BRACKETS,
	LPP_COORDINATION_DEDUCTION,
	LPP_ENTRY_THRESHOLD,
	LPP_MAXIMUM_COORDINATED_SALARY,
	LPP_MINIMUM_INSURED_SALARY,
	RATE_BASED_COMPONENTS,
	get_yearly_constants,
)
from hrms.regional.switzerland.rounding import round_to_5_centimes
from hrms.regional.switzerland.source_tax import round_half_up


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


def get_company_payroll_config(company, config=None):
	"""The company's default Swiss Social Insurance Config, for the rules that are the company's and
	not a canton's: its extra salaries, the value of a vacation day paid at the exit, its flat-rate
	expenses, how its salaries leave the bank. A canton's own configuration (an employee taxed
	elsewhere) keeps its insurance rates, not these. ``config`` is returned when the company has no
	default configuration."""
	# //// Neoffice — added (2026-09-24): see the docstring.
	default = frappe.db.get_value(
		"Swiss Social Insurance Config", {"company": company, "is_default": 1}, "*", as_dict=True
	)
	return default or config


def get_lpp_rate_for_age(age):
	"""Return the LPP/BVG contribution rate based on employee age.

	Returns the total rate (employee + employer combined).
	Below age 25 or above 65, returns 0 (not insured under BVG minimum).
	"""
	for bracket in LPP_AGE_BRACKETS:
		if bracket["min_age"] <= age <= bracket["max_age"]:
			return bracket["rate"]
	return 0


def calculate_lpp_coordinated_salary(annual_salary, config=None, year=None):
	"""Calculate the LPP/BVG coordinated (insured) salary.

	Applies the coordination deduction and enforces minimum/maximum thresholds.
	Priority: instance config -> yearly vintage (when year is given) ->
	module-level defaults.

	Args:
		annual_salary: Gross annual salary in CHF
		config: Optional SwissSocialInsuranceConfig dict with custom thresholds
		year: Optional payroll year for the published vintage

	Returns:
		The annual coordinated salary (amount on which LPP contributions are calculated)
	"""
	yearly = get_yearly_constants(year) if year else {}
	entry_threshold = (
		flt(config.get("lpp_entry_threshold") if config else 0)
		or yearly.get("lpp_entry_threshold")
		or LPP_ENTRY_THRESHOLD
	)
	coordination_deduction = (
		flt(config.get("lpp_coordination_deduction") if config else 0)
		or yearly.get("lpp_coordination_deduction")
		or LPP_COORDINATION_DEDUCTION
	)
	minimum_insured = (
		flt(config.get("lpp_minimum_insured_salary") if config else 0)
		or yearly.get("lpp_minimum_insured_salary")
		or LPP_MINIMUM_INSURED_SALARY
	)
	maximum_coordinated = (
		flt(config.get("lpp_maximum_coordinated_salary") if config else 0)
		or yearly.get("lpp_maximum_coordinated_salary")
		or LPP_MAXIMUM_COORDINATED_SALARY
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


def calculate_lpp_contribution(
	annual_salary, age, config=None, year=None, maintained_salary=0, maintained_employer_share=0
):
	"""Calculate monthly LPP/BVG contribution amounts for employee and employer.

	Args:
		annual_salary: Gross annual salary in CHF
		age: Employee age in years
		config: Optional SwissSocialInsuranceConfig dict
		maintained_salary: //// Neoffice — LPP art. 33a: the last insured annual salary the
			employee keeps insured after a salary cut from 58. The credits on the difference are
			outside the parity rule (art. 33a al. 3): the employee pays them, except for the
			``maintained_employer_share`` (%) the employer agreed to take.

	Returns:
		dict with keys: coordinated_salary, total_rate, total_annual,
		employee_monthly, employer_monthly
	"""
	coordinated_salary = calculate_lpp_coordinated_salary(annual_salary, config, year=year)
	total_rate = get_lpp_rate_for_age(age)

	maintained_coordinated = 0
	if flt(maintained_salary) > flt(annual_salary):
		maintained_coordinated = calculate_lpp_coordinated_salary(maintained_salary, config, year=year)

	if not total_rate or not (coordinated_salary or maintained_coordinated):
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

	if maintained_coordinated > coordinated_salary:
		extra = (maintained_coordinated - coordinated_salary) * total_rate
		employer_extra = extra * min(max(flt(maintained_employer_share), 0), 100) / 100
		employer_annual += employer_extra
		employee_annual += extra - employer_extra
		total_annual += extra
		coordinated_salary = maintained_coordinated

	return {
		"coordinated_salary": coordinated_salary,
		"total_rate": total_rate,
		"total_annual": total_annual,
		"employee_monthly": round_to_5_centimes(employee_annual / 12),
		"employer_monthly": round_to_5_centimes(employer_annual / 12),
	}


def calculate_ac_contribution(monthly_gross, ytd_gross, config=None, year=None, *, days_before, days_current):
	"""AC/ALV contribution of a month, under the ceiling cumulated pro rata temporis.

	//// Neoffice — was measured against the whole yearly ceiling from January: a leaver in
	//// June paid on 20'000 a month owed AC on 120'000 instead of 74'100 (6 x 12'350), and the
	//// months were never capped as the year went. Swissdec guidelines 7.12.3: the base
	//// cumulated over the year is compared with the ceiling prorated to the contribution days
	//// (148'200 x days / 360), minus what the previous months insured — see ceilings.py.

	No contribution at all above the ceiling: the AC solidarity contribution was abolished
	on 2023-01-01 (SECO communication of 2022-10-13; AHV/AVS leaflet 2.08).

	Args:
		monthly_gross: AC-subject salary of the month.
		ytd_gross: AC-subject salary of the year BEFORE this month.
		config: Optional SwissSocialInsuranceConfig dict.
		days_before, days_current: contribution days before and of this month
			(ceilings.contribution_period).

	Returns:
		dict with keys: ac_employee, ac_employer, subject_to_ac, exempt_above_ceiling
		(negative in a month that insures what earlier months could not).
	"""
	yearly = get_yearly_constants(year) if year else {}
	ceiling = (
		flt(config.get("ac_annual_ceiling") if config else 0)
		or yearly.get("ac_annual_ceiling")
		or AC_ANNUAL_CEILING
	)
	ac_rate_ee = flt(config.get("ac_rate_employee") if config else 0) / 100 or AC_RATE_EMPLOYEE
	ac_rate_er = flt(config.get("ac_rate_employer") if config else 0) / 100 or AC_RATE_EMPLOYER

	monthly_gross = flt(monthly_gross)
	subject_to_ac = month_insured(flt(ytd_gross), days_before, monthly_gross, days_current, 0, ceiling)

	return {
		"ac_employee": round_to_5_centimes(subject_to_ac * ac_rate_ee),
		"ac_employer": round_to_5_centimes(subject_to_ac * ac_rate_er),
		"subject_to_ac": subject_to_ac,
		"exempt_above_ceiling": flt(monthly_gross - subject_to_ac, 2),
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

	# //// Neoffice — getdate() answers None for anything it cannot parse — an int year, say —
	# //// and reference_date.year below then died with an AttributeError pointing at this line
	# //// instead of at the caller that passed the wrong thing. Name what was passed.
	parsed = getdate(reference_date) if reference_date else getdate(today())
	if parsed is None:
		raise ValueError(f"get_employee_age: unusable reference date {reference_date!r}")
	reference_date = parsed
	date_of_birth = getdate(date_of_birth)

	age = reference_date.year - date_of_birth.year
	if (reference_date.month, reference_date.day) < (date_of_birth.month, date_of_birth.day):
		age -= 1

	return age


# //// Neoffice — added. The LPP rates were read with the age to the day (get_employee_age):
# //// someone born in November 1991 was charged the 7 % credit until his birthday in 2026
# //// instead of 10 % from January, and a man of 65 kept paying 18 % until his 66th birthday.
# LPP art. 33b: a fund may keep insuring an employee who works past the reference age, at the
# latest until the age of 70.
LPP_CONTINUATION_LIMIT_AGE = 70


def get_lpp_age(employee, start_date, end_date):
	"""The LPP age of a pay period, or 0 once the AVS reference age is behind.

	The age that sets the savings credit is the calendar year minus the year of birth — every
	pension fund reads it so, whatever the birthday. The savings stop when the reference age
	is reached (LPP art. 13): from the month after it, no credit is due any more — unless the
	employee keeps working and asked to stay insured (LPP art. 33b, ch_lpp_after_reference_age):
	then the credit of the last bracket continues, through the month of the 70th birthday.
	"""
	from hrms.regional.switzerland.avs_exemption import age_in_year, is_past_reference_age
	from hrms.regional.switzerland.insurance_solutions import normalize_sex

	fields = ["date_of_birth", "gender"]
	if frappe.get_meta("Employee").has_field("ch_lpp_after_reference_age"):
		fields.append("ch_lpp_after_reference_age")
	values = frappe.db.get_value("Employee", employee, fields, as_dict=True) or {}
	if not values.get("date_of_birth"):
		return 0
	birth = getdate(values.date_of_birth)
	start = getdate(start_date or end_date)
	if is_past_reference_age(birth, normalize_sex(values.get("gender")), start):
		# Insured through the month of the 70th birthday, as the pension starts the month after.
		limit = add_months(birth.replace(day=1), LPP_CONTINUATION_LIMIT_AGE * 12 + 1)
		if not cint(values.get("ch_lpp_after_reference_age")) or start >= limit:
			return 0
		return LPP_AGE_BRACKETS[-1]["max_age"]
	return age_in_year(birth, getdate(end_date or start_date).year)


# //// Neoffice — added: LPP art. 33a, maintained insured salary.
LPP_MAINTENANCE_MIN_AGE = 58


def get_lpp_maintenance(employee, start_date):
	"""(maintained annual salary, employer share %) of LPP art. 33a for a pay period, or (0, 0).

	From 58, an employee whose salary dropped by half at most may keep the last insured salary
	insured, until the reference age at the latest (LPP art. 33a al. 1-2).
	"""
	from hrms.regional.switzerland.avs_exemption import is_past_reference_age
	from hrms.regional.switzerland.insurance_solutions import normalize_sex

	if not frappe.get_meta("Employee").has_field("ch_lpp_maintained_salary"):
		return 0, 0
	values = (
		frappe.db.get_value(
			"Employee",
			employee,
			["date_of_birth", "gender", "ch_lpp_maintained_salary", "ch_lpp_maintained_employer_share"],
			as_dict=True,
		)
		or {}
	)
	salary = flt(values.get("ch_lpp_maintained_salary"))
	if not salary or not values.get("date_of_birth"):
		return 0, 0
	start = getdate(start_date)
	birth = getdate(values.date_of_birth)
	if get_employee_age({"date_of_birth": birth}, start) < LPP_MAINTENANCE_MIN_AGE:
		return 0, 0
	if is_past_reference_age(birth, normalize_sex(values.get("gender")), start):
		return 0, 0
	return salary, flt(values.get("ch_lpp_maintained_employer_share"))


def get_ytd_gross_for_employee(employee, company, start_date, end_date):
	"""Get year-to-date gross salary for an employee, excluding the current period.

	#//// Neoffice — this said "Used for AC ceiling tracking". It is NOT: the ceiling is measured
	#//// against the AC-SUBJECT cumulative, which is get_ytd_ac_base_for_employee below. Summing
	#//// gross_pay counts earnings that owe no AC and moves the ceiling. Left in place because a
	#//// plain year-to-date gross is a legitimate figure of its own — just not this one.

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


# //// Neoffice — added. The AC ceiling has to be tracked against the AC-SUBJECT cumulative, not
# //// against gross pay: _update_ac_components measures this month with bases["ac_base"] (the
# //// earnings whose Salary Component carries ch_subject_to_ac) and used to compare it to
# //// get_ytd_gross_for_employee(), which sums gross_pay — everything, subject or not. Mixing the
# //// two moves the ceiling: an employee paid 12'000 a month of which 1'000 is not AC-subject
# //// reaches 144'000 of gross by December while owing AC on 132'000, and the ceiling of 148'200
# //// cuts December's base to 4'200 instead of 11'000. Employee and employer are both undercharged
# //// and the AVS settlement no longer matches. Same rule as _get_insurance_base_totals, applied
# //// to the slips already submitted: flagged components count where flagged, a component with no
# //// flag at all counts everywhere, and a slip on which nothing is flagged falls back to its whole
# //// earnings total (the backward-compatibility case of installations that never set the flags).
def get_ytd_ac_base_for_employee(employee, company, start_date, end_date):
	"""Year-to-date AC-subject salary for an employee, excluding the current period."""
	return get_ytd_insurance_bases(employee, company, start_date)["ac"]


# //// Neoffice — one definition of a component whose flags are to be trusted, shared by the
# //// payslip (payroll_hooks), the year-to-date bases below and the declaration (swissdec_data).
def is_configured_component(values):
	"""Whether a Salary Component's insurance flags are to be trusted as set.

	True when the component carries a Swiss wage type (its flags come from the catalogue, all
	zero included) or when any flag is set. A component with neither predates the flags: the
	callers then count it in every base, as before the flags existed.
	"""
	values = values or {}
	flags = (
		"ch_subject_to_avs",
		"ch_subject_to_ac",
		"ch_subject_to_laa",
		"ch_subject_to_ijm",
		"ch_subject_to_lpp",
		"ch_subject_to_imp",
	)
	return bool(
		any(cint(values.get(f)) for f in flags)
		or values.get("ch_wage_type")
		or values.get("ch_wage_type_code")
	)


INSURANCE_BASE_KEYS = ("avs", "ac", "laa", "ijm", "lpp", "imp")


# //// Neoffice — added: the payslip, the year-to-date ceilings, the declaration and the printed
# //// slip each summed their own bases and had already drifted apart (a component subject to
# //// nothing, 6000 expenses, was exempt on one side and charged on the other). One rule now,
# //// and it knows the two Swissdec behaviours a subject flag cannot express.
def sum_insurance_bases(rows):
	"""The insurance bases of a set of earning rows, and the gross they add up to.

	Each row carries its ``amount``, ``do_not_include_in_total`` and its component's
	ch_subject_to_* flags, ch_wage_type, ch_wage_type_code and ch_bases_only.

	* A row paid (in the total) counts in the gross, and in each base its component is
	  subject to — in every base when the component predates the flags.
	* A row left out of the total counts nowhere, unless its wage type counts in the bases
	  only (1920 tips, 2065 short-time work loss, Swissdec guidelines 6.0, 8.7.2.5): then in
	  the bases it is subject to, never in the gross, since nobody pays it.
	* A negative amount — a "-" wage type (2050 correction of a daily allowance, 2060
	  short-time work deduction) — takes back from each of them what it would have added.
	* When no row is configured at all, every base is the gross: installations that never
	  set the flags keep their old behaviour.

	Returns:
		dict with avs, ac, laa, ijm, lpp, imp and gross (floats), and configured (bool).
	"""
	totals = dict.fromkeys(INSURANCE_BASE_KEYS, 0.0)
	gross = 0.0
	configured = False
	for row in rows:
		if cint(row.get("do_not_include_in_total")) and not cint(row.get("ch_bases_only")):
			continue
		amount = flt(row.get("amount"))
		if not cint(row.get("do_not_include_in_total")):
			gross += amount
		row_configured = is_configured_component(row)
		configured = configured or row_configured
		for key in INSURANCE_BASE_KEYS:
			if not row_configured or cint(row.get(f"ch_subject_to_{key}")):
				totals[key] += amount
	if not configured:
		totals = dict.fromkeys(INSURANCE_BASE_KEYS, gross)
	return {**totals, "gross": gross, "configured": configured}


def get_ytd_insurance_bases(employee, company, start_date):
	"""Year-to-date AC-, LAA- and IJM-subject salaries of an employee, before ``start_date``.

	//// Neoffice — generalised from get_ytd_ac_base_for_employee: the LAA ceiling and the
	//// LAAC / IJM brackets are cumulated over the year too (guidelines 7.12.3), so they need
	//// their own year-to-date bases. Same rule as _get_insurance_base_totals, applied to the
	//// slips already submitted: flagged components count where flagged, a component with no
	//// flag at all counts everywhere, and a slip on which nothing is flagged falls back to its
	//// whole earnings total (installations that never set the flags).

	Returns:
		dict with ac, laa, ijm (floats) and first_start: the start of the first period of the
		year already paid in Neoffice, or None.
	"""
	year_start = getdate(start_date).replace(month=1, day=1)

	# //// Neoffice — the rows left out of the total are read too, and every slip goes through
	# //// sum_insurance_bases: a wage type that only raises the bases (1920, 2065) must count
	# //// in the ceilings of the months after, exactly as it counted in its own.
	rows = frappe.db.sql(
		"""
		SELECT
			sd.parent AS slip,
			ss.start_date AS slip_start,
			COALESCE(sd.amount, sd.default_amount, 0) AS amount,
			COALESCE(sd.do_not_include_in_total, 0) AS do_not_include_in_total,
			sc.ch_subject_to_avs, sc.ch_subject_to_ac, sc.ch_subject_to_laa,
			sc.ch_subject_to_ijm, sc.ch_subject_to_lpp, sc.ch_subject_to_imp,
			sc.ch_wage_type, sc.ch_wage_type_code, sc.ch_bases_only
		FROM `tabSalary Detail` sd
		INNER JOIN `tabSalary Slip` ss ON ss.name = sd.parent
		LEFT JOIN `tabSalary Component` sc ON sc.name = sd.salary_component
		WHERE ss.employee = %s
			AND ss.company = %s
			AND ss.start_date >= %s
			AND ss.end_date < %s
			AND ss.docstatus = 1
			AND sd.parenttype = 'Salary Slip'
			AND sd.parentfield = 'earnings'
		""",
		(employee, company, year_start, start_date),
		as_dict=True,
	)

	keys = ("ac", "laa", "ijm")
	per_slip = {}
	for row in rows:
		per_slip.setdefault(row.slip, []).append(row)
	slips = [sum_insurance_bases(slip_rows) for slip_rows in per_slip.values()]
	result = {key: flt(sum(bases[key] for bases in slips)) for key in keys}
	starts = [getdate(row.slip_start) for row in rows]
	result["first_start"] = min(starts) if starts else None
	return result


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

	# //// Neoffice — the LPP age the slip was computed with (utils.get_lpp_age), not the age to the day.
	age = get_lpp_age(doc.employee, doc.start_date, doc.end_date)
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

	# AC Solidarity: abolished 2023-01-01 — no longer displayed.

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
	config = get_swiss_social_insurance_config(doc.company, employee.get("ch_fiscal_canton") or "")
	# //// Neoffice — the LPP age the slip was computed with (get_lpp_age), not the age to the day.
	age = get_lpp_age(doc.employee, doc.start_date, doc.end_date)
	rates = _build_rate_dict(config, age) if config else {}

	# //// Neoffice — translated, was hardcoded French ("Madame" / "Monsieur"), so a
	# //// German- or Italian-speaking employee of a Swiss company received a French
	# //// payslip header. The French wording is unchanged, it now comes from the
	# //// catalogue (issue #239).
	# //// Neoffice — compared the raw gender with "Female" / "Male": an instance whose
	# //// Gender records are localised ("Féminin", "Masculin") printed no salutation at all.
	salutation = employee_salutation(employee)

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
	# //// Neoffice — the Swissdec layout of a payslip, as the certified engine prints it: expense
	# //// reimbursements (6000-6499) are listed after the deductions, not in the gross salary they
	# //// were inflating on the print; advances (6510, 6520) come off the net salary.
	expenses = []
	base_rows = []

	comp_fields = [
		"ch_wage_type",
		"ch_wage_type_code",
		"ch_subject_to_avs",
		"ch_subject_to_ac",
		"ch_subject_to_laa",
		"ch_subject_to_ijm",
		"ch_subject_to_lpp",
		"ch_subject_to_imp",
		"ch_bases_only",
	]

	for row in doc.get("earnings", []):
		comp_vals = (
			frappe.get_cached_value("Salary Component", row.salary_component, comp_fields, as_dict=True) or {}
		)
		gs_code = comp_vals.get("ch_wage_type_code") or ""
		entry = {
			"gs_code": gs_code,
			"name": row.salary_component,
			"amount": flt(row.amount, 2),
			# A row left out of the total (1920 tips, a bases-only wage type) is not paid: the
			# print shows it as a base, so that the amounts listed add up to the gross.
			"paid": not cint(row.get("do_not_include_in_total")),
		}
		if EXPENSE_WAGE_TYPES[0] <= _wage_type_number(gs_code) < EXPENSE_WAGE_TYPES[1]:
			expenses.append(entry)
		else:
			earnings.append(entry)

		# //// Neoffice — the amounts PAID, exactly as the payroll hook builds its bases. It read
		# //// default_amount first: on a partial month the payslip printed the full monthly salary
		# //// as the base of contributions computed on half of it.
		amount = flt(row.default_amount if row.get("amount") is None else row.amount, 2)
		base_rows.append(
			{**comp_vals, "amount": amount, "do_not_include_in_total": row.get("do_not_include_in_total")}
		)

	# //// Neoffice — the payslip's own rule (sum_insurance_bases). This loop had a third one: a
	# //// component without flags counted in no base at all as soon as another one had flags,
	# //// where the hook counts it in every base.
	summed = sum_insurance_bases(base_rows)
	insurance_bases = {key: summed[key] for key in (*INSURANCE_BASE_KEYS, "gross")}

	# //// Neoffice — the bases the payroll hook actually used, where the slip carries them:
	# //// after the AVS exemption of a pensioner, the AC ceiling and the LAA cap. The sums of
	# //// earnings above stay for the slips computed before the hook recorded its bases.
	stored = _stored_contribution_bases(doc)
	for key, components in (
		("avs", ("AVS/AI/APG Employee", "AVS/AI/APG Employer")),
		("ac", ("AC/ALV Employee", "AC/ALV Employer")),
		("laa", ("LAA Non-Professional Employee", "LAA Professional Employer")),
	):
		recorded = next((stored[c]["base"] for c in components if c in stored), None)
		if recorded is not None:
			insurance_bases[key] = recorded

	# Build enriched deductions (employee and employer separate)
	deductions_ee = []
	deductions_er = []
	after_net = []
	total_ee = 0
	total_er = 0

	for row in doc.get("deductions", []):
		if not flt(row.amount):
			continue
		comp_name = row.salary_component
		is_employer = comp_name in employer_set
		comp_vals = (
			frappe.get_cached_value("Salary Component", comp_name, ["ch_wage_type_code"], as_dict=True) or {}
		)
		gs_code = comp_vals.get("ch_wage_type_code") or ""

		rate_str = rates.get(comp_name, "")
		recorded = stored.get(comp_name)
		if recorded:
			# //// Neoffice — the base and rate the amount was computed with (see _record_base in
			# //// payroll_hooks). Derived back from the amount they are wrong once amounts round
			# //// to 5 centimes, and the configuration's flat rate is not the rate of a business
			# //// unit or of an insurance code.
			determinant = recorded.get("base") or 0
			if "rate" in recorded:
				rate_str = _format_rate(recorded["rate"])
		else:
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
		elif _wage_type_number(gs_code) >= EXPENSE_WAGE_TYPES[1]:
			after_net.append(entry)
		else:
			deductions_ee.append(entry)
			total_ee += flt(row.amount, 2)

	# //// Neoffice — upstream takes a loan repayment off the net without a deduction row: listed
	# //// with the advances, the amounts printed add up to the net paid.
	if flt(doc.get("total_loan_repayment")):
		after_net.append(
			{
				"gs_code": "",
				"name": "Loan Repayment",
				"determinant": 0,
				"rate": "",
				"amount": flt(doc.total_loan_repayment, 2),
			}
		)

	gross = flt(sum(row["amount"] for row in earnings if row["paid"]), 2)
	expenses_total = flt(sum(row["amount"] for row in expenses if row["paid"]), 2)

	# Period label
	try:
		end = getdate(doc.end_date)
		# //// Neoffice — the framework formats the month in the reader's language.
		# //// It was a hardcoded French month list, so the period on every payslip read
		# //// French whatever the employee's language (issue #239). In French the output
		# //// is unchanged: babel gives "septembre 2026", capitalised to "Septembre 2026".
		label = formatdate(end, "MMMM yyyy")
		period_label = label[:1].upper() + label[1:]
	except Exception:
		period_label = ""

	# Company logo
	company_logo = company_doc.get("company_logo") or ""

	# //// Neoffice — what the certified engine prints about the employment (position, entry and
	# //// exit dates, activity rate) and the source tax tariff: the canton and code THIS slip was
	# //// settled with (ch_qst_canton, kept per slip), which the employee checks the tax against.
	# //// The paid days show only for a partial month: on a full one they merely repeated the
	# //// calendar ("31 working days" in May).
	work_percentage = flt(employee.get("ch_work_percentage"))
	partial = flt(doc.payment_days) < flt(doc.total_working_days)
	employment = {
		"designation": employee.get("designation") or "",
		"date_of_joining": employee.get("date_of_joining"),
		"relieving_date": employee.get("relieving_date"),
		"work_percentage": _format_number(work_percentage) if work_percentage else "",
		"pay_days": f"{_format_number(doc.payment_days)} / {_format_number(doc.total_working_days)}"
		if partial
		else "",
	}
	source_tax = None
	if doc.get("ch_qst_tariff_code"):
		source_tax = {
			"canton": doc.get("ch_qst_canton")
			or employee.get("ch_qst_taxation_canton")
			or employee.get("ch_fiscal_canton")
			or "",
			"tariff": doc.ch_qst_tariff_code,
		}

	net = flt(doc.net_pay, 2)
	return {
		"employee": employee,
		"salutation": salutation,
		"address_lines": address_lines,
		"company_address": company_address,
		"company_uid": company_doc.get("tax_id") or "",
		"company_logo": company_logo,
		"period_label": period_label,
		"employment": employment,
		"source_tax": source_tax,
		"earnings": earnings,
		"expenses": expenses,
		"deductions_ee": deductions_ee,
		"after_net": after_net,
		"deductions_er": deductions_er,
		"insurance_bases": insurance_bases,
		"totals": {
			"gross": gross,
			"ee_deductions": flt(total_ee, 2),
			"expenses": expenses_total,
			# The net salary (Swissdec 6500) before the advances; the net paid after them.
			"net_salary": flt(net + sum(row["amount"] for row in after_net), 2),
			"net": net,
			# //// Neoffice — only when it differs from the net: a Swiss slip pays its net
			# //// (payroll_hooks._pay_the_net_as_computed), older slips carry a franc rounding.
			"rounded": flt(doc.rounded_total, 2)
			if doc.rounded_total and flt(doc.rounded_total, 2) != flt(doc.net_pay, 2)
			else 0,
			"er_contributions": flt(total_er, 2),
			"employer_cost": flt(doc.gross_pay, 2) + flt(total_er, 2),
		},
		# //// Neoffice — no amount in words any more: an Indian accounting convention that no Swiss
		# //// payslip carries, and that printed "Quatre Mille Six Cent ... seulement".
		"bank": _get_bank_details(doc, employee),
		# //// Neoffice — a Swiss Post WebStamp ordered for this slip (webstamp.py): it carries the
		# //// franking AND the recipient address, so the print puts it in the envelope window.
		"webstamp_image": get_webstamp_image(doc),
	}


def employee_salutation(employee):
	"""Mrs / Mr as the payslip addresses the employee, "" when the gender says neither."""
	from hrms.regional.switzerland.insurance_solutions import SEX_FEMALE, SEX_MALE, normalize_sex

	sex = normalize_sex(employee.get("gender"))
	if sex == SEX_FEMALE:
		return _("Mrs")
	if sex == SEX_MALE:
		# //// Neoffice — see the block marker in get_salary_slip_print_data: translated, was
		# //// hardcoded French.
		return _("Mr")
	return ""


def get_webstamp_image(doc):
	"""URL of the WebStamp ordered for this document, or None.

	The order record of the swisspost_barcode app is the source of truth, the stamp file attached
	to the document the fallback; a site without that app has neither and gets None.
	"""
	if not doc.get("name"):
		return None
	if frappe.db.table_exists("SwissPost Webstamp Order"):
		url = frappe.db.get_value(
			"SwissPost Webstamp Order",
			{"document_type": doc.doctype, "document_name": doc.name, "stamp_file": ["is", "set"]},
			"stamp_file",
			order_by="creation desc",
		)
		if url:
			return url
	return frappe.db.get_value(
		"File",
		{
			"attached_to_doctype": doc.doctype,
			"attached_to_name": doc.name,
			"file_name": ["like", "stamp\\_%"],
		},
		"file_url",
		order_by="creation desc",
	)


# Swissdec wage types reimbursed after the net salary: expenses, 6000 to 6499. Deductions from
# 6500 upwards (6510 advance, 6520 payments on account) come off the net salary itself.
EXPENSE_WAGE_TYPES = (6000, 6500)


def _wage_type_number(code):
	"""The numeric wage type of a component's code, 0 when it has none."""
	try:
		return int(str(code).strip())
	except (TypeError, ValueError):
		return 0


def _format_number(value):
	"""16.0 -> "16", 62.5 -> "62.5": days and percentages as a person writes them."""
	return f"{flt(value):g}"


def _mask_account(value):
	"""An account number as a payslip prints it: its first and last four characters only.

	A payslip travels (a landlord, a bank asks for the last three); the employee recognises
	the account by its ends, as on the certified engine's payslip.
	"""
	compact = (value or "").replace(" ", "")
	if len(compact) <= 8:
		return compact
	masked = compact[:4] + "•" * (len(compact) - 8) + compact[-4:]
	return " ".join(masked[i : i + 4] for i in range(0, len(masked), 4))


def _get_bank_details(doc, employee):
	"""Get bank details from salary slip, employee, or linked Bank Account."""
	bank_name = doc.bank_name or employee.get("bank_name") or ""
	account_no = doc.bank_account_no or employee.get("bank_ac_no") or ""
	iban = ""

	# Try to find IBAN from Bank Account linked to employee
	if not iban:
		bank_account = frappe.db.get_value(
			"Bank Account",
			{"party_type": "Employee", "party": doc.employee, "is_default": 1},
			["bank", "bank_account_no", "iban"],
			as_dict=True,
		)
		if bank_account:
			if not bank_name:
				bank_name = bank_account.get("bank") or ""
			if not account_no:
				account_no = bank_account.get("bank_account_no") or ""
			iban = bank_account.get("iban") or ""

	# //// Neoffice — the payslip prints the account masked, and says IBAN when it is one: the
	# //// employee wizard records the IBAN in bank_ac_no, which printed as a bare "Account".
	account = iban or account_no
	return {
		"bank_name": bank_name,
		"account_no": account_no,
		"iban": iban,
		"masked": _mask_account(account),
		"is_iban": bool(iban) or bool(IBAN_PATTERN.match(account.replace(" ", "").upper())),
	}


IBAN_PATTERN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{8,30}$")


def _stored_contribution_bases(doc):
	"""{component: {"base": x[, "rate": y]}} recorded on the slip by the payroll hook, or {}."""
	value = doc.get("ch_contribution_bases")
	if not value:
		return {}
	try:
		parsed = frappe.parse_json(value)
	except Exception:
		return {}
	return parsed if isinstance(parsed, dict) else {}


def _format_rate(rate):
	"""A recorded rate as the payslip prints it: "" for none, otherwise like the configuration."""
	if rate in ("", None):
		return ""
	return str(flt(rate, 4))


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
			return round_half_up(abs(amount) / (rate / 100))
		return insurance_bases.get("ac", 0)

	# LPP/BVG: back-calculate from amount and rate (coordinated salary)
	if "LPP/BVG" in comp_name:
		rate = flt(rate_str)
		if rate and amount:
			return round_half_up(abs(amount) / (rate / 100))
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
