# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.utils import cint, flt

from hrms.regional.switzerland.constants import RATE_BASED_COMPONENTS
from hrms.regional.switzerland.source_tax import calculate_source_tax
from hrms.regional.switzerland.utils import (
	calculate_ac_contribution,
	calculate_lpp_contribution,
	calculate_thirteenth_month,
	get_employee_age,
	get_swiss_social_insurance_config,
	get_ytd_gross_for_employee,
)


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

	# Add 13th month earning if applicable (before computing gross)
	updated = _add_thirteenth_month_earning(doc, config)

	# Base monthly salary from "Basic" component (used for LPP annualization)
	base_monthly = _get_base_from_earnings(doc)
	if not base_monthly:
		return

	# Gross pay = sum of all earnings (including 13th month if added).
	# Swiss law requires ALL salary earnings to be subject to social charges.
	# NOTE: Expense reimbursements (Spesen) are NOT subject to social charges
	# if covered by an approved expense regulation (Spesenreglement). They must
	# be processed via the Expense Claim module, not as salary earning components.
	gross_pay = sum(flt(row.default_amount) for row in doc.get("earnings"))

	# Update rate-based components (AVS, LAA, IJM, Family) on gross_pay
	updated = _update_rate_based_components(doc, config, gross_pay) or updated

	# Update AC/ALV with ceiling tracking on gross_pay
	updated = _update_ac_components(doc, config, gross_pay) or updated

	# Update LPP/BVG: annualize using base_monthly * multiplier (13 if 13th enabled)
	thirteenth_mode = config.get("thirteenth_month_mode") or "Disabled"
	lpp_multiplier = 13 if thirteenth_mode != "Disabled" else 12
	updated = _update_lpp_components(doc, config, base_monthly, lpp_multiplier, employee) or updated

	# Update Source Tax (Quellensteuer) if enabled
	if config.get("qst_enabled") and employee.get("ch_qst_subject"):
		updated = _update_source_tax(doc, config, employee, gross_pay) or updated

	if updated:
		_recalculate_totals(doc)


def _get_base_from_earnings(doc):
	"""Get the base salary from earnings if doc.base is not set."""
	for row in doc.get("earnings"):
		if row.salary_component == "Basic" or row.abbr == "B":
			return flt(row.default_amount)
	return 0


def _update_rate_based_components(doc, config, gross_pay):
	"""Update components that are calculated as a simple percentage of gross pay."""
	updated = False

	for row in doc.get("deductions"):
		if row.salary_component in RATE_BASED_COMPONENTS:
			rate_field, _is_employer = RATE_BASED_COMPONENTS[row.salary_component]
			rate = flt(config.get(rate_field))
			if rate:
				full_amount = flt(gross_pay * rate / 100, row.precision("amount"))
				prorated = _prorate_amount(doc, row, full_amount)
				if prorated != flt(row.amount, row.precision("amount")):
					row.default_amount = full_amount
					row.amount = prorated
					updated = True

	return updated


def _update_ac_components(doc, config, gross_pay):
	"""Update AC/ALV components with annual ceiling tracking."""
	updated = False

	ytd_gross = get_ytd_gross_for_employee(doc.employee, doc.company, doc.start_date, doc.end_date)

	ac_result = calculate_ac_contribution(gross_pay, ytd_gross, config)

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


def _update_lpp_components(doc, config, base_monthly, lpp_multiplier, employee):
	"""Update LPP/BVG components based on employee age."""
	updated = False

	age = get_employee_age(doc.employee, doc.end_date)
	annual_salary = base_monthly * lpp_multiplier  # 13 if 13th month enabled, 12 otherwise

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


def _add_thirteenth_month_earning(doc, config):
	"""Add 13th month salary earning to the slip if applicable.

	Returns True if an earning row was added, False otherwise.
	Skips if the component already exists (manual override via Additional Salary).
	"""
	thirteenth_mode = config.get("thirteenth_month_mode") or "Disabled"
	if thirteenth_mode == "Disabled":
		return False

	# Skip if already present (manual override)
	for row in doc.get("earnings"):
		if row.salary_component == "13th Month Salary":
			return False

	if not frappe.db.exists("Salary Component", "13th Month Salary"):
		return False

	base_monthly = _get_base_from_earnings(doc)
	if not base_monthly:
		return False

	amount = calculate_thirteenth_month(base_monthly, doc.employee, doc.start_date, doc.end_date, config)

	if not amount:
		return False

	_add_earning_row(doc, "13th Month Salary", amount)
	return True


def _add_earning_row(doc, component_name, amount):
	"""Add a new earning row to the salary slip."""
	comp = frappe.get_cached_doc("Salary Component", component_name)

	row = doc.append("earnings", {})
	row.salary_component = component_name
	row.abbr = comp.salary_component_abbr
	row.do_not_include_in_total = comp.do_not_include_in_total
	row.depends_on_payment_days = comp.depends_on_payment_days
	row.default_amount = flt(amount, row.precision("amount"))
	row.amount = flt(amount, row.precision("amount"))


def _update_source_tax(doc, config, employee, gross_pay):
	"""Update the Source Tax Employee deduction based on ESTV tariff brackets."""
	updated = False

	result = calculate_source_tax(employee, doc, config)
	tax_amount = flt(result.get("tax_amount", 0), 2)

	# Find or add the Source Tax component
	found = False
	for row in doc.get("deductions"):
		if row.salary_component == "Source Tax Employee":
			found = True
			if flt(row.amount, 2) != tax_amount:
				row.default_amount = tax_amount
				row.amount = tax_amount
				updated = True
			break

	if not found and tax_amount:
		_add_deduction_row(doc, "Source Tax Employee", tax_amount)
		# Source tax is not prorated — override the default proration
		for row in doc.get("deductions"):
			if row.salary_component == "Source Tax Employee":
				row.default_amount = tax_amount
				row.amount = tax_amount
				break
		updated = True

	return updated


def _recalculate_totals(doc):
	"""Recalculate salary slip totals after component amounts have been updated."""
	doc.set_net_pay()
	doc.compute_year_to_date()
	doc.compute_month_to_date()
