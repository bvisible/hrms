# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Source tax (Quellensteuer / Impôt à la source) calculation engine.

Handles both the monthly model (21 cantons) and the annual model
(FR, GE, TI, VD, VS) for withholding tax on salary income.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from hrms.regional.switzerland.constants import ANNUAL_MODEL_CANTONS


def get_calculation_model(canton):
	"""Return the calculation model for a canton.

	Args:
		canton: 2-letter canton code (e.g., "ZH", "GE").

	Returns:
		"annual" for FR/GE/TI/VD/VS, "monthly" for all others.
	"""
	if canton and canton.upper() in ANNUAL_MODEL_CANTONS:
		return "annual"
	return "monthly"


def build_tariff_code(letter, num_children, church_tax):
	"""Build a 3-character ESTV tariff code.

	Args:
		letter: Tariff category letter (A, B, C, E, G, H, L, M, N, P, Q).
		num_children: Number of children for tax purposes (0-9).
		church_tax: Whether the employee is a church tax member.

	Returns:
		3-character tariff code (e.g., "B2Y", "A0N").
	"""
	letter = (letter or "A").upper()[:1]
	children = max(0, min(9, int(num_children or 0)))
	church = "Y" if church_tax else "N"
	return f"{letter}{children}{church}"


def lookup_qst_rate(canton, tariff_code, income, reference_date, tariff_type="SAL"):
	"""Look up the source tax rate for a given income bracket.

	Uses the composite index on Swiss QST Tariff Bracket for fast lookup.

	Args:
		canton: 2-letter canton code.
		tariff_code: 3-character tariff code (e.g., "B2Y").
		income: Gross income amount in CHF.
		reference_date: Date for determining which tariff is valid.
		tariff_type: "SAL" for salary, "VSL" for other income.

	Returns:
		Tax rate as decimal (e.g., 0.0525 for 5.25%), or 0 if no bracket found.
	"""
	income = flt(income)
	if income <= 0:
		return 0

	result = frappe.db.sql(
		"""SELECT tax_rate FROM `tabSwiss QST Tariff Bracket`
		WHERE canton = %s AND tariff_code = %s AND tariff_type = %s
			AND valid_from <= %s AND income_from <= %s
		ORDER BY valid_from DESC, income_from DESC
		LIMIT 1""",
		(canton.upper(), tariff_code, tariff_type, reference_date, income),
		as_dict=True,
	)

	return flt(result[0].tax_rate, 6) if result else 0


def calculate_source_tax_monthly(
	gross, canton, tariff_code, ref_date, tariff_type="SAL", qst_days=30, aperiodic=0.0
):
	"""Calculate source tax using the monthly model.

	Used by 21 cantons (all except FR, GE, TI, VD, VS).
	Rate lookup on the rate-determining salary, tax = gross × rate.

	For a partial month (entry/exit mid-month) the periodic part of the
	salary is extrapolated to 30 days to determine the rate; aperiodic
	payments (bonus, back pay) are added without extrapolation. Validated
	against Swissdec Annex 1 (e.g. M17: 5750 over 15 days -> determinant
	11500). With qst_days=30 and aperiodic=0 this reduces to the plain
	lookup on gross.

	Args:
		gross: Monthly gross salary in CHF (periodic + aperiodic).
		canton: 2-letter canton code.
		tariff_code: 3-character tariff code.
		ref_date: Reference date for tariff validity.
		tariff_type: "SAL" or "VSL".
		qst_days: Source-tax days in the month (30 = full month, base 360).
		aperiodic: Aperiodic portion of gross (not extrapolated).

	Returns:
		dict with tax_amount, tax_rate, determinant, model.
	"""
	gross = flt(gross)
	if gross <= 0:
		return {"tax_amount": 0, "tax_rate": 0, "determinant": 0, "model": "monthly"}

	qst_days = flt(qst_days) or 30
	aperiodic = flt(aperiodic)
	periodic = gross - aperiodic
	determinant = round(periodic / qst_days * 30 + aperiodic, 2)

	rate = lookup_qst_rate(canton, tariff_code, determinant, ref_date, tariff_type)
	tax = round(gross * rate, 2)

	return {
		"tax_amount": tax,
		"tax_rate": rate,
		"determinant": determinant,
		"model": "monthly",
	}


def calculate_source_tax_annual(
	gross,
	canton,
	tariff_code,
	ytd_gross,
	ytd_tax,
	month_num,
	ref_date,
	tariff_type="SAL",
	qst_days=30,
	ytd_days=None,
	aperiodic=0.0,
	ytd_aperiodic=0.0,
):
	"""Calculate source tax using the annual model.

	Used by 5 cantons: FR, GE, TI, VD, VS.
	Annualizes the cumulative periodic income over the cumulative
	source-tax days (base 360), adds aperiodic payments without
	extrapolation, looks up the rate on the annualized/12 determinant,
	then withholds cumulative-due minus already-deducted.

	Validated against Swissdec Annex 1 (e.g. Y17 exit June 15th:
	35750 over 165 days -> annualized 78000, determinant 6500,
	due 35750 x 12.4% = 4433, June = 4433 - 3450 = 983). With full
	months and no aperiodic split this reduces to the historical
	cumulative-average projection (cum/months x 12).

	Args:
		gross: Current month gross salary in CHF (periodic + aperiodic).
		canton: 2-letter canton code.
		tariff_code: 3-character tariff code.
		ytd_gross: Year-to-date gross BEFORE this month.
		ytd_tax: Year-to-date source tax already deducted.
		month_num: Current employment month number in the year (1-12).
		ref_date: Reference date for tariff validity.
		tariff_type: "SAL" or "VSL".
		qst_days: Source-tax days of this month (30 = full, base 360).
		ytd_days: Cumulative source-tax days BEFORE this month
			(defaults to (month_num - 1) x 30 = all prior months full).
		aperiodic: Aperiodic portion of this month's gross.
		ytd_aperiodic: Aperiodic portion of ytd_gross.

	Returns:
		dict with tax_amount, tax_rate, determinant, projected_annual,
		cumulative_due, model.
	"""
	gross = flt(gross)
	ytd_gross = flt(ytd_gross)
	ytd_tax = flt(ytd_tax)
	month_num = max(1, min(12, int(month_num)))

	if gross <= 0:
		return {
			"tax_amount": 0,
			"tax_rate": 0,
			"determinant": 0,
			"projected_annual": 0,
			"cumulative_due": 0,
			"model": "annual",
		}

	qst_days = flt(qst_days) or 30
	if ytd_days is None:
		ytd_days = (month_num - 1) * 30
	total_days = flt(ytd_days) + qst_days

	total_gross = ytd_gross + gross
	total_aperiodic = flt(ytd_aperiodic) + flt(aperiodic)
	total_periodic = total_gross - total_aperiodic

	# Annualize periodic income over source-tax days; aperiodic added as is.
	projected_annual = round(total_periodic / total_days * 360 + total_aperiodic, 2)

	# Look up rate based on the monthly determinant (annual / 12)
	determinant = round(projected_annual / 12, 2)
	rate = lookup_qst_rate(canton, tariff_code, determinant, ref_date, tariff_type)

	# Cumulative tax due on the actual cumulative gross
	cumulative_due = round(total_gross * rate, 2)

	# This month's tax = cumulative due - already deducted
	this_month_tax = round(cumulative_due - ytd_tax, 2)

	# Never negative (in case of overpayment, it will correct in subsequent months)
	# Exception: December can be negative for annual correction
	if month_num < 12 and this_month_tax < 0:
		this_month_tax = 0

	return {
		"tax_amount": this_month_tax,
		"tax_rate": rate,
		"determinant": determinant,
		"projected_annual": projected_annual,
		"cumulative_due": cumulative_due,
		"model": "annual",
	}


def tariff_code_exists(canton, tariff_code, reference_date, tariff_type="SAL"):
	"""Return True if at least one bracket exists for this canton/code/type/date."""
	result = frappe.db.sql(
		"""SELECT 1 FROM `tabSwiss QST Tariff Bracket`
		WHERE canton = %s AND tariff_code = %s AND tariff_type = %s
			AND valid_from <= %s
		LIMIT 1""",
		(canton.upper(), tariff_code, tariff_type, reference_date),
	)
	return bool(result)


def ensure_tariff_available(canton, tariff_code, reference_date, tariff_type="SAL"):
	"""Fail loudly when no tariff data exists for a source-taxed employee.

	A silent 0% withholding on a subject employee is a compliance risk (the
	employer stays liable for the missing tax). Raised for: tariffs not yet
	imported for the year, or a tariff code the canton does not publish —
	e.g. Geneva has no church tax at source, so no "…Y" codes exist there.
	"""
	if tariff_code_exists(canton, tariff_code, reference_date, tariff_type):
		return
	hint = ""
	if str(tariff_code).upper().endswith("Y"):
		hint = " " + _(
			"Note: some cantons (e.g. GE) levy no church tax at source and only publish '…N' codes."
		)
	frappe.throw(
		_(
			"No source tax bracket found for canton {0}, tariff code {1}, date {2}. "
			"Import the ESTV tariffs for this year or fix the employee's tariff code.{3}"
		).format(canton, tariff_code, reference_date, hint),
		title=_("Source Tax Tariff Missing"),
	)


def calculate_source_tax(employee_doc, salary_slip_doc, config):
	"""Main entry point: calculate source tax for a salary slip.

	Determines the calculation model (monthly/annual) based on canton,
	builds the tariff code from employee data, and dispatches to the
	appropriate calculator.

	Args:
		employee_doc: Employee document (or dict-like with QST fields).
		salary_slip_doc: Salary Slip document.
		config: Swiss Social Insurance Config dict.

	Returns:
		dict with tax_amount and other calculation details.
	"""
	# Determine taxation canton
	canton = (
		employee_doc.get("ch_qst_taxation_canton")
		or employee_doc.get("ch_fiscal_canton")
		or config.get("qst_default_canton")
		or ""
	)

	if not canton:
		return {"tax_amount": 0, "error": "no_canton"}

	# Build tariff code from employee fields
	tariff_code = employee_doc.get("ch_qst_tariff_code") or build_tariff_code(
		employee_doc.get("ch_qst_tariff_letter"),
		employee_doc.get("ch_qst_num_children"),
		employee_doc.get("ch_qst_church_tax"),
	)

	if not tariff_code:
		return {"tax_amount": 0, "error": "no_tariff_code"}

	# Gross pay from the salary slip (sum of all earnings)
	gross = sum(flt(row.default_amount) for row in salary_slip_doc.get("earnings"))

	ref_date = salary_slip_doc.end_date or salary_slip_doc.start_date

	# Never withhold 0 silently because tariff data is missing
	if gross > 0:
		ensure_tariff_available(canton, tariff_code, ref_date)

	model = get_calculation_model(canton)

	if model == "monthly":
		result = calculate_source_tax_monthly(gross, canton, tariff_code, ref_date)
	else:
		# Annual model: need YTD data
		ytd_data = get_qst_ytd_data(
			salary_slip_doc.employee, salary_slip_doc.company, salary_slip_doc.start_date
		)
		month_num = getdate(salary_slip_doc.end_date).month
		result = calculate_source_tax_annual(
			gross,
			canton,
			tariff_code,
			ytd_data["ytd_gross"],
			ytd_data["ytd_tax"],
			month_num,
			ref_date,
		)

	# Apply cross-border rules if enabled
	if config.get("cb_enabled") and employee_doc.get("ch_is_cross_border"):
		from hrms.regional.switzerland.cross_border import get_cross_border_tax

		result = get_cross_border_tax(employee_doc, salary_slip_doc, config, result)

	# Check 120k threshold
	check_120k_threshold(
		salary_slip_doc.employee,
		salary_slip_doc.company,
		gross,
		salary_slip_doc.start_date,
		config,
	)

	return result


def get_qst_ytd_data(employee, company, start_date):
	"""Get year-to-date gross salary and source tax from submitted salary slips.

	Used for the annual model calculation.

	Args:
		employee: Employee ID.
		company: Company name.
		start_date: Start date of the current payroll period.

	Returns:
		dict with ytd_gross and ytd_tax.
	"""
	year_start = getdate(start_date).replace(month=1, day=1)

	result = frappe.db.sql(
		"""SELECT
			COALESCE(SUM(ss.gross_pay), 0) as ytd_gross,
			COALESCE(SUM(
				(SELECT COALESCE(SUM(sd.amount), 0)
				 FROM `tabSalary Detail` sd
				 WHERE sd.parent = ss.name
					AND sd.parentfield = 'deductions'
					AND sd.salary_component = 'Source Tax Employee')
			), 0) as ytd_tax
		FROM `tabSalary Slip` ss
		WHERE ss.employee = %s
			AND ss.company = %s
			AND ss.start_date >= %s
			AND ss.end_date < %s
			AND ss.docstatus = 1""",
		(employee, company, year_start, start_date),
		as_dict=True,
	)

	if result:
		return {"ytd_gross": flt(result[0].ytd_gross), "ytd_tax": flt(result[0].ytd_tax)}

	return {"ytd_gross": 0, "ytd_tax": 0}


def check_120k_threshold(employee, company, current_gross, start_date, config):
	"""Check if employee's projected annual income exceeds the ordinary taxation threshold.

	Sets the ch_qst_120k_flag on the Employee record if threshold is exceeded.
	This is informational only — the employer continues to withhold source tax.

	Args:
		employee: Employee ID.
		company: Company name.
		current_gross: Current month's gross salary.
		start_date: Start date of the current payroll period.
		config: Swiss Social Insurance Config dict.
	"""
	threshold = flt(config.get("qst_ordinary_threshold")) or 120000

	# Get YTD gross
	year_start = getdate(start_date).replace(month=1, day=1)
	result = frappe.db.sql(
		"""SELECT COALESCE(SUM(ss.gross_pay), 0) as ytd_gross
		FROM `tabSalary Slip` ss
		WHERE ss.employee = %s
			AND ss.company = %s
			AND ss.start_date >= %s
			AND ss.end_date < %s
			AND ss.docstatus = 1""",
		(employee, company, year_start, start_date),
		as_dict=True,
	)

	ytd_gross = flt(result[0].ytd_gross) if result else 0
	total_gross = ytd_gross + flt(current_gross)
	month_num = max(1, getdate(start_date).month)
	projected_annual = total_gross / month_num * 12

	exceeds = 1 if projected_annual > threshold else 0

	current_flag = frappe.db.get_value("Employee", employee, "ch_qst_120k_flag")
	if current_flag != exceeds:
		frappe.db.set_value("Employee", employee, "ch_qst_120k_flag", exceeds)


def auto_fetch_new_tariffs():
	"""Scheduled daily task: check for and import next year's ESTV tariffs.

	ESTV typically publishes tariffs in early December. This job runs daily
	and imports tariffs for the upcoming year if not yet available.
	Only runs between December 1 and January 15.
	"""
	from frappe.utils import nowdate

	today = getdate(nowdate())

	# Only run in the Dec 1 - Jan 15 window
	if not ((today.month == 12 and today.day >= 1) or (today.month == 1 and today.day <= 15)):
		return

	# Determine target year
	target_year = today.year if today.month <= 6 else today.year + 1

	for tariff_type_abbr, tariff_type_label in (("SAL", "Salaires"), ("VSL", "Autres revenus")):
		existing = frappe.db.count(
			"Swiss QST Tariff",
			{"year": target_year, "tariff_type_abbr": tariff_type_abbr, "status": "Active"},
		)
		if existing < 26:
			try:
				from hrms.payroll.doctype.swiss_qst_tariff.swiss_qst_tariff import fetch_all_cantons

				fetch_all_cantons(target_year, tariff_type_label)
			except Exception as e:
				frappe.log_error("QST auto-fetch failed", str(e))
