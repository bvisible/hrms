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

	# Compute per-insurance-base totals from earnings.
	# Each earning's Salary Component has ch_subject_to_* flags that determine
	# which insurance bases it contributes to. Falls back to sum(all earnings)
	# if no flags are configured (backward compatibility).
	bases = _get_insurance_base_totals(doc)

	# Update rate-based components using the appropriate base for each
	updated = _update_rate_based_components(doc, config, bases) or updated

	# Update AC/ALV with ceiling tracking using the AC base
	updated = _update_ac_components(doc, config, bases["ac_base"]) or updated

	# Update LPP/BVG: annualize using base_monthly * multiplier (13 if 13th enabled)
	thirteenth_mode = config.get("thirteenth_month_mode") or "Disabled"
	lpp_multiplier = 13 if thirteenth_mode != "Disabled" else 12
	updated = _update_lpp_components(doc, config, base_monthly, lpp_multiplier, employee) or updated

	# Update Source Tax (Quellensteuer) if enabled
	if config.get("qst_enabled") and employee.get("ch_qst_subject"):
		updated = _update_source_tax(doc, config, employee, bases["imp_base"]) or updated

	if updated:
		_recalculate_totals(doc)


def _get_insurance_base_totals(doc):
	"""Compute per-insurance-base totals from earnings.

	For each earning row, looks up the Salary Component's ch_subject_to_* flags
	and accumulates amounts into the corresponding base totals.

	Backward compatibility: if NO earning has any ch_subject_to_* flag set
	(all are 0 or NULL), falls back to sum(all earnings) for all bases.
	This handles installations where the flags have not yet been configured.

	Returns:
		dict with keys: avs_base, ac_base, laa_base, ijm_base, lpp_base, imp_base, gross_total
	"""
	gross_total = 0
	avs_base = 0
	ac_base = 0
	laa_base = 0
	ijm_base = 0
	lpp_base = 0
	imp_base = 0
	any_flag_configured = False

	for row in doc.get("earnings"):
		amount = flt(row.default_amount)
		gross_total += amount

		# Fetch insurance base flags from the Salary Component
		flags = _get_component_insurance_flags(row.salary_component)

		if flags["has_flags"]:
			any_flag_configured = True
			if flags["avs"]:
				avs_base += amount
			if flags["ac"]:
				ac_base += amount
			if flags["laa"]:
				laa_base += amount
			if flags["ijm"]:
				ijm_base += amount
			if flags["lpp"]:
				lpp_base += amount
			if flags["imp"]:
				imp_base += amount
		else:
			# No flags configured on this component — accumulate into all bases
			avs_base += amount
			ac_base += amount
			laa_base += amount
			ijm_base += amount
			lpp_base += amount
			imp_base += amount

	# Backward compatibility: if no component had any flag configured,
	# all bases equal gross_total (same as the old behavior)
	if not any_flag_configured:
		return {
			"avs_base": gross_total,
			"ac_base": gross_total,
			"laa_base": gross_total,
			"ijm_base": gross_total,
			"lpp_base": gross_total,
			"imp_base": gross_total,
			"gross_total": gross_total,
		}

	return {
		"avs_base": avs_base,
		"ac_base": ac_base,
		"laa_base": laa_base,
		"ijm_base": ijm_base,
		"lpp_base": lpp_base,
		"imp_base": imp_base,
		"gross_total": gross_total,
	}


def _get_component_insurance_flags(component_name):
	"""Get the Swiss social insurance base flags for a Salary Component.

	Returns a dict with boolean flags for each insurance base plus a
	has_flags indicator that is True if at least one flag is explicitly set.
	Uses frappe.get_cached_value for performance.
	"""
	fields = [
		"ch_subject_to_avs",
		"ch_subject_to_ac",
		"ch_subject_to_laa",
		"ch_subject_to_ijm",
		"ch_subject_to_lpp",
		"ch_subject_to_imp",
	]

	values = frappe.get_cached_value("Salary Component", component_name, fields, as_dict=True)

	if not values:
		return {"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0, "has_flags": False}

	avs = cint(values.get("ch_subject_to_avs"))
	ac = cint(values.get("ch_subject_to_ac"))
	laa = cint(values.get("ch_subject_to_laa"))
	ijm = cint(values.get("ch_subject_to_ijm"))
	lpp = cint(values.get("ch_subject_to_lpp"))
	imp = cint(values.get("ch_subject_to_imp"))

	# has_flags is True if at least one flag is explicitly 1
	# This distinguishes "all flags = 0" (configured as exempt) from "not configured"
	has_flags = bool(avs or ac or laa or ijm or lpp or imp)

	return {"avs": avs, "ac": ac, "laa": laa, "ijm": ijm, "lpp": lpp, "imp": imp, "has_flags": has_flags}


def _get_base_from_earnings(doc):
	"""Get the base salary from earnings if doc.base is not set."""
	for row in doc.get("earnings"):
		if row.salary_component == "Basic" or row.abbr == "B":
			return flt(row.default_amount)
	return 0


def _update_rate_based_components(doc, config, bases):
	"""Update components that are calculated as a simple percentage of their insurance base.

	Also adds missing component rows that may have been removed by remove_if_zero_valued
	during salary slip generation.
	"""
	updated = False

	# Track which components are already in the slip
	existing_components = {row.salary_component for row in doc.get("deductions")}

	for row in doc.get("deductions"):
		if row.salary_component in RATE_BASED_COMPONENTS:
			rate_field, _is_employer, base_type = RATE_BASED_COMPONENTS[row.salary_component]
			rate = flt(config.get(rate_field))
			base_amount = flt(bases.get(base_type, bases["gross_total"]))
			if rate:
				full_amount = flt(base_amount * rate / 100, row.precision("amount"))
				prorated = _prorate_amount(doc, row, full_amount)
				if prorated != flt(row.amount, row.precision("amount")):
					row.default_amount = full_amount
					row.amount = prorated
					updated = True

	# Add missing rate-based components (removed by remove_if_zero_valued)
	for comp_name, (rate_field, _is_employer, base_type) in RATE_BASED_COMPONENTS.items():
		if comp_name in existing_components:
			continue
		rate = flt(config.get(rate_field))
		base_amount = flt(bases.get(base_type, bases["gross_total"]))
		if rate and base_amount:
			amount = flt(base_amount * rate / 100, 2)
			if amount:
				_add_deduction_row(doc, comp_name, amount)
				updated = True

	return updated


def _update_ac_components(doc, config, ac_base):
	"""Update AC/ALV components with annual ceiling tracking."""
	updated = False

	ytd_gross = get_ytd_gross_for_employee(doc.employee, doc.company, doc.start_date, doc.end_date)

	ac_result = calculate_ac_contribution(ac_base, ytd_gross, config)

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

	# Add missing LPP rows (removed by remove_if_zero_valued)
	for comp_name, amount in lpp_mapping.items():
		amount = flt(amount, 2)
		if amount and not _has_component(doc, comp_name):
			_add_deduction_row(doc, comp_name, amount)
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


def _update_source_tax(doc, config, employee, imp_base):
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
