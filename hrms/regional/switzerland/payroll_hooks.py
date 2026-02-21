# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.utils import cint, flt

from hrms.regional.switzerland.utils import (
	calculate_ac_contribution,
	calculate_lpp_contribution,
	get_employee_age,
	get_swiss_social_insurance_config,
	get_ytd_gross_for_employee,
)

# Map of component names to config rate fields
RATE_BASED_COMPONENTS = {
	"AVS/AI/APG Employee": ("avs_rate_employee", False),
	"AVS/AI/APG Employer": ("avs_rate_employer", True),
	"LAA Professional Employer": ("laa_professional_rate", True),
	"LAA Non-Professional Employee": ("laa_nonprofessional_rate", False),
	"IJM/KTG Employee": ("ijm_rate_employee", False),
	"IJM/KTG Employer": ("ijm_rate_employer", True),
	"Family Allowances Employer": ("family_allowance_rate", True),
}


def update_swiss_social_contributions(doc, method):
	"""Hook on Salary Slip validate to calculate Swiss social contributions.

	Called after the standard validate() has run, including calculate_net_pay().
	Updates deduction amounts for Swiss social charge components based on
	the Swiss Social Insurance Config, then recalculates totals.
	"""
	company_country = frappe.get_cached_value("Company", doc.company, "country")
	if company_country != "Switzerland":
		return

	employee = frappe.get_cached_doc("Employee", doc.employee)
	canton = employee.get("ch_fiscal_canton") or ""
	config = get_swiss_social_insurance_config(doc.company, canton)

	if not config:
		return

	base_salary = flt(doc.base) or _get_base_from_earnings(doc)
	if not base_salary:
		return

	updated = False

	# Update rate-based components (AVS, LAA, IJM, Family)
	updated = _update_rate_based_components(doc, config, base_salary) or updated

	# Update AC/ALV with ceiling tracking
	updated = _update_ac_components(doc, config, base_salary) or updated

	# Update LPP/BVG with age-based calculation
	updated = _update_lpp_components(doc, config, base_salary, employee) or updated

	if updated:
		_recalculate_totals(doc)


def _get_base_from_earnings(doc):
	"""Get the base salary from earnings if doc.base is not set."""
	for row in doc.get("earnings"):
		if row.salary_component == "Basic" or row.abbr == "B":
			return flt(row.amount)
	return 0


def _update_rate_based_components(doc, config, base_salary):
	"""Update components that are calculated as a simple percentage of base salary."""
	updated = False

	for row in doc.get("deductions"):
		if row.salary_component in RATE_BASED_COMPONENTS:
			rate_field, _is_employer = RATE_BASED_COMPONENTS[row.salary_component]
			rate = flt(config.get(rate_field))
			if rate:
				full_amount = flt(base_salary * rate / 100, row.precision("amount"))
				prorated = _prorate_amount(doc, row, full_amount)
				if prorated != flt(row.amount, row.precision("amount")):
					row.default_amount = full_amount
					row.amount = prorated
					updated = True

	return updated


def _update_ac_components(doc, config, base_salary):
	"""Update AC/ALV components with annual ceiling tracking."""
	updated = False

	ytd_gross = get_ytd_gross_for_employee(doc.employee, doc.company, doc.start_date, doc.end_date)

	ac_result = calculate_ac_contribution(base_salary, ytd_gross, config)

	ac_mapping = {
		"AC/ALV Employee": ac_result["ac_employee"],
		"AC/ALV Employer": ac_result["ac_employer"],
		"AC Solidarity Employee": ac_result["solidarity_employee"],
		"AC Solidarity Employer": ac_result["solidarity_employer"],
	}

	for row in doc.get("deductions"):
		if row.salary_component in ac_mapping:
			full_amount = flt(ac_mapping[row.salary_component], row.precision("amount"))
			prorated = _prorate_amount(doc, row, full_amount)
			if prorated != flt(row.amount, row.precision("amount")):
				row.default_amount = full_amount
				row.amount = prorated
				updated = True

	# Add solidarity rows if they have amounts but weren't in the slip
	for comp_name in ("AC Solidarity Employee", "AC Solidarity Employer"):
		amount = flt(ac_mapping.get(comp_name, 0), 2)
		if amount and not _has_component(doc, comp_name):
			_add_deduction_row(doc, comp_name, amount)
			updated = True

	return updated


def _update_lpp_components(doc, config, base_salary, employee):
	"""Update LPP/BVG components based on employee age."""
	updated = False

	age = get_employee_age(doc.employee, doc.end_date)
	annual_salary = base_salary * 12  # annualize monthly base

	lpp_result = calculate_lpp_contribution(annual_salary, age, config)

	lpp_mapping = {
		"LPP/BVG Employee": lpp_result["employee_monthly"],
		"LPP/BVG Employer": lpp_result["employer_monthly"],
	}

	for row in doc.get("deductions"):
		if row.salary_component in lpp_mapping:
			full_amount = flt(lpp_mapping[row.salary_component], row.precision("amount"))
			prorated = _prorate_amount(doc, row, full_amount)
			if prorated != flt(row.amount, row.precision("amount")):
				row.default_amount = full_amount
				row.amount = prorated
				updated = True

	return updated


def _prorate_amount(doc, row, amount):
	"""Apply payment day proration to a component amount.

	Matches the standard Frappe HRMS behavior: when depends_on_payment_days
	is set and the employee has fewer payment days than total working days,
	the amount is prorated accordingly.
	"""
	if (
		cint(row.depends_on_payment_days)
		and cint(doc.total_working_days)
		and doc.payment_days != doc.total_working_days
	):
		return flt(amount * flt(doc.payment_days) / flt(doc.total_working_days), row.precision("amount"))
	return flt(amount, row.precision("amount"))


def _has_component(doc, component_name):
	"""Check if a salary component already exists in the slip deductions."""
	for row in doc.get("deductions"):
		if row.salary_component == component_name:
			return True
	return False


def _add_deduction_row(doc, component_name, amount):
	"""Add a new deduction row to the salary slip."""
	comp = frappe.get_cached_doc("Salary Component", component_name)

	row = doc.append("deductions", {})
	row.salary_component = component_name
	row.abbr = comp.salary_component_abbr
	row.do_not_include_in_total = comp.do_not_include_in_total
	row.depends_on_payment_days = comp.depends_on_payment_days
	row.default_amount = flt(amount, row.precision("amount"))
	row.amount = _prorate_amount(doc, row, row.default_amount)


def _recalculate_totals(doc):
	"""Recalculate salary slip totals after component amounts have been updated."""
	doc.set_net_pay()
	doc.compute_year_to_date()
	doc.compute_month_to_date()
