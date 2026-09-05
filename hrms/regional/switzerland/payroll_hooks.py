#//// Neoffice — added file (no upstream equivalent): Salary Slip validate hook computing the Swiss
#//// social contributions and source tax. Wired in hooks.py doc_events.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.utils import cint, flt

#//// Neoffice — BASE_SALARY_WAGE_TYPE_CODES added: hourly, per-lesson and weekly pay are
#//// base pay too, see _is_base_wage_type.
from hrms.regional.switzerland.constants import BASE_SALARY_WAGE_TYPE_CODES, RATE_BASED_COMPONENTS
from hrms.regional.switzerland.source_tax import calculate_source_tax, round_half_up
from hrms.regional.switzerland.utils import (
	calculate_ac_contribution,
	calculate_lpp_contribution,
	calculate_thirteenth_month,
	get_employee_age,
	get_swiss_social_insurance_config,
	#//// Neoffice — was get_ytd_gross_for_employee; the AC ceiling tracks the AC-subject
	#//// cumulative, not gross pay. See _update_ac_components.
	get_ytd_ac_base_for_employee,
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

	#//// Neoffice — the early return that stood here aborted the WHOLE hook whenever no base
	#//// salary component was found on the slip: an employee paid by the hour (wage type 1005)
	#//// got no AVS, no AC, no LAA, no IJM and no source tax at all — silently under-deducted,
	#//// and under-declared. The base is only needed to ANNUALIZE LPP, so only LPP may be
	#//// skipped for want of it (see below).
	# Base salary of the month (used for LPP annualization)
	base_monthly = _get_base_from_earnings(doc)

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
	#//// Neoffice — an employee paid by the hour has no fixed monthly base: annualize the
	#//// LPP-subject earnings actually paid this month, which is what the annualization
	#//// approximates for a monthly salary anyway. With nothing to annualize at all, skip LPP
	#//// alone and SAY so — never drop the other contributions, as the early return used to.
	lpp_base_monthly = base_monthly or flt(bases["lpp_base"])
	if lpp_base_monthly:
		updated = (
			_update_lpp_components(doc, config, lpp_base_monthly, lpp_multiplier, employee) or updated
		)
	elif flt(bases["gross_total"]):
		_warn_no_lpp_base(doc)

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
		if cint(row.get("do_not_include_in_total")):
			continue
		# Amounts actually paid: on a partial month row.amount is prorated
		# while default_amount stays full. Ceilings (AC/LAA) must apply to
		# the real base, so no downstream proration of the results either.
		amount = flt(row.default_amount if row.get("amount") is None else row.amount)
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


def _warn_no_lpp_base(doc):
	#//// Neoffice — added with the fix above: a contribution that cannot be computed has to be
	#//// visible. Silence is what let the hourly-employee bug survive — the slip simply came out
	#//// without LPP and looked normal.
	"""Report that LPP was skipped for want of a base, instead of dropping it silently."""
	message = frappe._(
		"LPP/BVG was not computed for {0}: no base salary could be determined on this slip "
		"(no earning carries a base wage type, and none is subject to LPP). The other Swiss "
		"contributions were computed normally."
	).format(doc.employee)
	frappe.log_error(
		"Swiss payroll: no LPP base on a salary slip", f"{doc.name or doc.employee}: {message}"
	)
	frappe.msgprint(message, title=frappe._("LPP/BVG skipped"), indicator="orange")


#//// Neoffice — docstring updated with the fix below: the base is no longer the monthly
#//// salary alone.
def _get_base_from_earnings(doc):
	"""Get the base salary of the month from the slip's earnings.
	The base component is identified by its Swissdec wage type (1000 monthly,
	1005 hourly, 1006 per lesson, 1007 weekly) rather than by a hard-coded
	name: the component may be called "Basic", "Salaire mensuel",
	"Monatslohn"… depending on the instance's wage type catalog. Falls back
	to the historical name/abbr match for setups without the catalog.
	"""
	for row in doc.get("earnings"):
		if _is_base_wage_type(row.salary_component):
			return flt(row.default_amount)
	for row in doc.get("earnings"):
		if row.salary_component == "Basic" or row.abbr == "B":
			return flt(row.default_amount)
	return 0


def _is_base_wage_type(component_name):
	#//// Neoffice — was `== 1000` (monthly salary only). Every other form of base pay — hourly,
	#//// per lesson, weekly — then looked like "no salary at all" to the caller.
	"""True when the salary component carries a Swissdec base-pay wage type."""
	if not component_name:
		return False
	wage_type = frappe.get_cached_value("Salary Component", component_name, "ch_wage_type")
	if not wage_type:
		return False
	code = frappe.get_cached_value("Swiss Wage Type", wage_type, "code")
	#//// Neoffice — was `== 1000`, see above.
	return cint(code) in BASE_SALARY_WAGE_TYPE_CODES


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
				# The base already reflects the prorated amounts paid, so the
				# result is final — prorating it again would double-count.
				amount = round_half_up(base_amount * rate / 100, row.precision("amount") or 2)
				if amount != flt(row.amount, row.precision("amount")):
					row.default_amount = amount
					row.amount = amount
					updated = True

	# Add missing rate-based components (removed by remove_if_zero_valued)
	for comp_name, (rate_field, _is_employer, base_type) in RATE_BASED_COMPONENTS.items():
		if comp_name in existing_components:
			continue
		rate = flt(config.get(rate_field))
		base_amount = flt(bases.get(base_type, bases["gross_total"]))
		if rate and base_amount:
			#//// Neoffice — prorate=False, and round_half_up like the loop above. The base is
			#//// built from the amounts ACTUALLY PAID, so it already carries the proration of a
			#//// partial month; _add_deduction_row used to apply payment_days/total_working_days
			#//// on top of it. An employee paid half the month had this contribution deducted at
			#//// a quarter — and only on the components the structure did not carry, so the same
			#//// slip mixed correct and quartered lines.
			amount = round_half_up(base_amount * rate / 100, 2)
			if amount:
				_add_deduction_row(doc, comp_name, amount, prorate=False)
				updated = True

	return updated


def _update_ac_components(doc, config, ac_base):
	"""Update AC/ALV components with annual ceiling tracking."""
	updated = False

	#//// Neoffice — was get_ytd_gross_for_employee (SUM of gross_pay). The ceiling was measuring
	#//// an AC-SUBJECT month against an ALL-EARNINGS year, so any earning that is not subject to
	#//// AC still pushed the employee towards the ceiling and cut the AC base of the month that
	#//// crosses it. See get_ytd_ac_base_for_employee for the worked example.
	ytd_ac_base = get_ytd_ac_base_for_employee(doc.employee, doc.company, doc.start_date, doc.end_date)

	from frappe.utils import getdate

	ac_result = calculate_ac_contribution(
		#//// Neoffice — second argument was ytd_gross; it is the AC-subject cumulative that the
		#//// ceiling is measured against, see get_ytd_ac_base_for_employee.
		ac_base, ytd_ac_base, config, year=getdate(doc.end_date).year
	)

	ac_mapping = {
		"AC/ALV Employee": ac_result["ac_employee"],
		"AC/ALV Employer": ac_result["ac_employer"],
		# Legacy rows from before the 2023 abolition of the solidarity
		# contribution are forced to zero if still present on a structure.
		"AC Solidarity Employee": 0,
		"AC Solidarity Employer": 0,
	}

	for row in doc.get("deductions"):
		if row.salary_component in ac_mapping:
			amount = flt(ac_mapping[row.salary_component], row.precision("amount"))
			if amount != flt(row.amount, row.precision("amount")):
				row.default_amount = amount
				row.amount = amount
				updated = True

	return updated


def _update_lpp_components(doc, config, base_monthly, lpp_multiplier, employee):
	"""Update LPP/BVG components based on employee age."""
	updated = False

	age = get_employee_age(doc.employee, doc.end_date)
	annual_salary = base_monthly * lpp_multiplier  # 13 if 13th month enabled, 12 otherwise

	from frappe.utils import getdate

	lpp_result = calculate_lpp_contribution(
		annual_salary, age, config, year=getdate(doc.end_date).year
	)

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
		return round_half_up(
			amount * flt(doc.payment_days) / flt(doc.total_working_days),
			row.precision("amount") or 2,
		)
	return flt(amount, row.precision("amount"))


def _has_component(doc, component_name):
	"""Check if a salary component already exists in the slip deductions."""
	for row in doc.get("deductions"):
		if row.salary_component == component_name:
			return True
	return False


#//// Neoffice — prorate added. Proration is not idempotent: an amount computed on a base
#//// that is already prorated must be stored as it is. See the call in
#//// _update_rate_based_components.
def _add_deduction_row(doc, component_name, amount, prorate=True):
	"""Add a new deduction row to the salary slip.

	prorate=False when the amount was computed on an already-prorated base."""
	comp = frappe.get_cached_doc("Salary Component", component_name)

	row = doc.append("deductions", {})
	row.salary_component = component_name
	row.abbr = comp.salary_component_abbr
	row.do_not_include_in_total = comp.do_not_include_in_total
	row.depends_on_payment_days = comp.depends_on_payment_days
	row.default_amount = flt(amount, row.precision("amount"))
	#//// Neoffice — see the prorate parameter above.
	row.amount = _prorate_amount(doc, row, row.default_amount) if prorate else row.default_amount


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
	# The stored amount is the prorated one (like frappe's own rows and
	# _add_deduction_row): the slip total prorates from default_amount, so
	# an unprorated amount here shows a wrong line on a partial month.
	row.amount = _prorate_amount(doc, row, row.default_amount)


def _resolve_component_by_wage_type(code, fallback_name):
	"""Resolve a Salary Component by its Swissdec wage type code.

	Component names vary per instance (English setup names vs. the French
	wage type catalog), so the stable identifier is the wage type code.
	Falls back to the historical name when no component carries the code.
	Returns None when neither exists.
	"""
	wage_type = frappe.db.get_value("Swiss Wage Type", {"code": code}, "name")
	if wage_type:
		component = frappe.db.get_value("Salary Component", {"ch_wage_type": wage_type}, "name")
		if component:
			return component
	if frappe.db.exists("Salary Component", fallback_name):
		return fallback_name
	return None


def _is_aperiodic_component(component_name, thirteenth_mode):
	"""True when the component's wage type is an aperiodic payment.

	Derived from the catalog's statistical category: "VU" (one-off
	payments — bonuses, gratifications, anniversary gifts) is always
	aperiodic; "SMS" (13th month) only when it is NOT paid monthly —
	Annex 1 treats the monthly twelfth and the pro-rata exit payment as
	periodic (M17/M21) but a lump 13th as aperiodic.
	"""
	if not component_name:
		return False
	wage_type = frappe.get_cached_value("Salary Component", component_name, "ch_wage_type")
	if not wage_type:
		return False
	category = frappe.get_cached_value("Swiss Wage Type", wage_type, "statistical_category")
	if category == "VU":
		return True
	if category == "SMS":
		return (thirteenth_mode or "Disabled") != "Monthly"
	return False


#//// Neoffice — restricted to the source-tax base with the imp_base fix below: the caller
#//// subtracts this total from that base to get the periodic part, so an aperiodic row that is
#//// NOT subject to source tax would make the periodic part too small — negative, even.
def _get_aperiodic_total(doc, config):
	"""Sum of the aperiodic earnings actually paid on this slip and subject to source tax."""
	thirteenth_mode = config.get("thirteenth_month_mode") or "Disabled"
	total = 0.0
	for row in doc.get("earnings"):
		if cint(row.get("do_not_include_in_total")):
			continue
		#//// Neoffice — see the note above the function: only the source-tax base counts here.
		flags = _get_component_insurance_flags(row.salary_component)
		if flags["has_flags"] and not flags["imp"]:
			continue
		if _is_aperiodic_component(row.salary_component, thirteenth_mode):
			total += flt(row.default_amount if row.get("amount") is None else row.amount)
	return round(total, 2)


def _update_source_tax(doc, config, employee, imp_base):
	"""Update the Source Tax Employee deduction based on ESTV tariff brackets."""
	updated = False

	aperiodic = _get_aperiodic_total(doc, config)
	#//// Neoffice — imp_base is passed on now. The caller computed it from the
	#//// ch_subject_to_imp flag of every component and this function dropped it:
	#//// calculate_source_tax summed ALL the earnings instead, so a component explicitly
	#//// marked as not subject to source tax was taxed like any other — and the tariff being
	#//// progressive, it also pushed the rate of everything else up.
	result = calculate_source_tax(employee, doc, config, aperiodic=aperiodic, gross=imp_base)
	tax_amount = flt(result.get("tax_amount", 0), 2)

	# Audit trail for retroactive corrections: the tariff code this slip
	# was settled with, and the corrections applied in this run.
	if result.get("tariff_code") and hasattr(doc, "ch_qst_tariff_code"):
		doc.ch_qst_tariff_code = result["tariff_code"]
	if hasattr(doc, "ch_qst_aperiodic"):
		doc.ch_qst_aperiodic = aperiodic
	if hasattr(doc, "ch_qst_correction_details"):
		corrections = result.get("corrections") or []
		if corrections:
			lines = []
			for corr in corrections:
				line = frappe._("{0} ({1}): {2} -> {3}").format(
					corr["slip"], corr["period"], corr["old_code"], corr["new_code"]
				)
				if corr.get("delta") is not None:
					line += f" ({flt(corr['delta']):+.2f})"
				lines.append(line)
			doc.ch_qst_correction_details = "\n".join(lines)
		else:
			doc.ch_qst_correction_details = None

	# Resolve the component by wage type 5060 (names vary per instance)
	component = _resolve_component_by_wage_type(5060, "Source Tax Employee")
	if not component:
		# A subject employee without an installed component would be silently
		# under-withheld — refuse to save the slip instead.
		frappe.throw(
			frappe._(
				"Employee {0} is subject to source tax but no salary component is "
				"linked to wage type 5060 (and 'Source Tax Employee' does not exist). "
				"Run the Swiss payroll setup or create the component."
			).format(doc.employee),
			title=frappe._("Source Tax Component Missing"),
		)

	# Find or add the Source Tax component
	found = False
	for row in doc.get("deductions"):
		if row.salary_component == component:
			found = True
			if flt(row.amount, 2) != tax_amount:
				row.default_amount = tax_amount
				row.amount = tax_amount
				updated = True
			break

	if not found and tax_amount:
		#//// Neoffice — prorate=False replaces the loop that used to undo the proration right
		#//// after _add_deduction_row applied it. Source tax is computed on the salary actually
		#//// paid and on the source-tax days of the period; it is never prorated again.
		_add_deduction_row(doc, component, tax_amount, prorate=False)
		updated = True

	return updated


def _recalculate_totals(doc):
	"""Recalculate salary slip totals after component amounts have been updated."""
	doc.gross_pay = doc.get_component_totals("earnings", depends_on_payment_days=1)
	doc.base_gross_pay = flt(
		flt(doc.gross_pay) * flt(doc.exchange_rate), doc.precision("base_gross_pay")
	)
	doc.set_net_pay()
	doc.compute_year_to_date()
	doc.compute_month_to_date()
