# //// Neoffice — added file (no upstream equivalent): Salary Slip validate hook computing the Swiss
# //// social contributions and source tax. Wired in hooks.py doc_events.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

# //// Neoffice — BASE_SALARY_WAGE_TYPE_CODES added: hourly, per-lesson and weekly pay are
# //// base pay too, see _is_base_wage_type.
from hrms.regional.switzerland.avs_exemption import apply_avs_status, resolve_avs_status
from hrms.regional.switzerland.ceilings import contribution_period, month_insured
from hrms.regional.switzerland.constants import (
	AVS_STATUS_EXEMPTED,
	AVS_STATUS_RETIRED,
	AVS_STATUS_RETIRED_WAIVED,
	AVS_STATUS_YOUTH,
	BASE_SALARY_WAGE_TYPE_CODES,
	LAA_INSURABLE_SALARY_CAP,
	RATE_BASED_COMPONENTS,
)
from hrms.regional.switzerland.rounding import round_to_5_centimes
from hrms.regional.switzerland.source_tax import calculate_source_tax
from hrms.regional.switzerland.utils import (
	calculate_ac_contribution,
	calculate_lpp_contribution,
	calculate_thirteenth_month,
	get_employee_age,
	get_swiss_social_insurance_config,
	# //// Neoffice — was get_ytd_gross_for_employee; the AC ceiling tracks the AC-subject
	# //// cumulative, not gross pay. See _update_ac_components. Now the LAA, LAAC and IJM
	# //// cumulatives as well: every ceiling is cumulated over the year (guidelines 7.12.3).
	get_ytd_insurance_bases,
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

	# The base and rate of every contribution, as computed below — the payslip prints them.
	doc.flags.ch_contribution_bases = {}

	# Add 13th month earning if applicable (before computing gross)
	updated = _add_thirteenth_month_earning(doc, config)

	# //// Neoffice — the early return that stood here aborted the WHOLE hook whenever no base
	# //// salary component was found on the slip: an employee paid by the hour (wage type 1005)
	# //// got no AVS, no AC, no LAA, no IJM and no source tax at all — silently under-deducted,
	# //// and under-declared. The base is only needed to ANNUALIZE LPP, so only LPP may be
	# //// skipped for want of it (see below).
	# Base salary of the month (used for LPP annualization)
	base_monthly = _get_base_from_earnings(doc)

	# Compute per-insurance-base totals from earnings.
	# Each earning's Salary Component has ch_subject_to_* flags that determine
	# which insurance bases it contributes to. Falls back to sum(all earnings)
	# if no flags are configured (backward compatibility).
	bases = _get_insurance_base_totals(doc)

	# //// Neoffice — narrow the AVS and AC bases for an employee who is under the
	# //// contribution start age or past the reference age. Without this an apprentice
	# //// under 18 was charged AVS and AC he does not owe, and a working pensioner paid
	# //// AVS on his whole salary instead of only the part above CHF 1'400/month — and
	# //// AC, which is not due past the reference age at all.
	bases = _apply_avs_status_to_bases(doc, bases)

	# //// Neoffice — every insurance ceiling is cumulated over the year and prorated to the
	# //// contribution days (Swissdec guidelines 7.12.3, see ceilings.py): the bases of the
	# //// months already paid, and the days before and of this period.
	ytd = get_ytd_insurance_bases(doc.employee, doc.company, doc.start_date)
	period = _contribution_period(doc, employee, ytd)

	# Update rate-based components using the appropriate base for each
	updated = _update_rate_based_components(doc, config, bases, ytd, period) or updated

	# Update AC/ALV with ceiling tracking using the AC base
	updated = (
		_update_ac_components(doc, config, bases["ac_base"], ytd, period, bases.get("ac_exempt")) or updated
	)

	# Update LPP/BVG: annualize using base_monthly * multiplier (13 if 13th enabled)
	thirteenth_mode = config.get("thirteenth_month_mode") or "Disabled"
	lpp_multiplier = 13 if thirteenth_mode != "Disabled" else 12
	# //// Neoffice — an employee paid by the hour has no fixed monthly base: annualize the
	# //// LPP-subject earnings actually paid this month, which is what the annualization
	# //// approximates for a monthly salary anyway. With nothing to annualize at all, skip LPP
	# //// alone and SAY so — never drop the other contributions, as the early return used to.
	lpp_base_monthly = base_monthly or flt(bases["lpp_base"])
	if lpp_base_monthly:
		updated = _update_lpp_components(doc, config, lpp_base_monthly, lpp_multiplier, employee) or updated
	elif flt(bases["gross_total"]):
		_warn_no_lpp_base(doc)

	# Update Source Tax (Quellensteuer) if enabled
	if config.get("qst_enabled") and employee.get("ch_qst_subject"):
		updated = _update_source_tax(doc, config, employee, bases["imp_base"]) or updated

	if updated:
		_recalculate_totals(doc)

	_store_contribution_bases(doc)
	_pay_the_net_as_computed(doc)


def _apply_avs_status_to_bases(doc, bases):
	"""Adjust the AVS and AC bases for the employee's declared AVS status.

	The status is read from the employee; the age is only used to catch someone
	below the contribution start age when nothing was declared. A missing date of
	birth means the age is UNKNOWN, never zero — otherwise every employee without
	a birth date would be treated as a minor and exempted from AVS and AC.
	"""
	employee = (
		frappe.db.get_value("Employee", doc.employee, ["ch_avs_status", "date_of_birth"], as_dict=True) or {}
	)
	age = get_employee_age(doc.employee, doc.end_date) if employee.get("date_of_birth") else None
	year = getdate(doc.end_date).year if doc.end_date else None
	status = resolve_avs_status(employee.get("ch_avs_status"), age, year=year)
	if not status:
		return bases

	adjusted = apply_avs_status(bases["avs_base"], bases["ac_base"], status, months=1, year=year)
	bases = dict(bases)
	bases["avs_base"] = adjusted["avs_base"]
	bases["ac_base"] = adjusted["ac_base"]
	# No AC is due at all — not even the catch-up a cumulated ceiling would otherwise find
	# room for in a month with a zero base.
	bases["ac_exempt"] = status in (
		AVS_STATUS_YOUTH,
		AVS_STATUS_EXEMPTED,
		AVS_STATUS_RETIRED,
		AVS_STATUS_RETIRED_WAIVED,
	)
	return bases


def _contribution_period(doc, employee, ytd):
	"""(days before, days of) this slip's period, for the insurance ceilings (ceilings.py).

	Counted from 1 January or the entry — but never before the first period of the year
	paid in Neoffice. For a company onboarded in September, what January to August paid
	elsewhere is unknown here; counting those months would lend the ceiling room they
	already used, and charge AC on a whole salary above it.
	"""
	start = getdate(doc.start_date)
	entry = employee.get("ch_entry_date") or employee.get("date_of_joining")
	exit_date = employee.get("ch_exit_date") or employee.get("relieving_date")
	first_paid = ytd.get("first_start") or start
	begins = max(getdate(entry), first_paid) if entry else first_paid
	return contribution_period(
		begins, getdate(exit_date) if exit_date else None, start, getdate(doc.end_date)
	)


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
	# //// Neoffice — added with the fix above: a contribution that cannot be computed has to be
	# //// visible. Silence is what let the hourly-employee bug survive — the slip simply came out
	# //// without LPP and looked normal.
	"""Report that LPP was skipped for want of a base, instead of dropping it silently."""
	message = frappe._(
		"LPP/BVG was not computed for {0}: no base salary could be determined on this slip "
		"(no earning carries a base wage type, and none is subject to LPP). The other Swiss "
		"contributions were computed normally."
	).format(doc.employee)
	frappe.log_error("Swiss payroll: no LPP base on a salary slip", f"{doc.name or doc.employee}: {message}")
	frappe.msgprint(message, title=frappe._("LPP/BVG skipped"), indicator="orange")


# //// Neoffice — docstring updated with the fix below: the base is no longer the monthly
# //// salary alone.
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
	# //// Neoffice — was `== 1000` (monthly salary only). Every other form of base pay — hourly,
	# //// per lesson, weekly — then looked like "no salary at all" to the caller.
	"""True when the salary component carries a Swissdec base-pay wage type."""
	if not component_name:
		return False
	wage_type = frappe.get_cached_value("Salary Component", component_name, "ch_wage_type")
	if not wage_type:
		return False
	code = frappe.get_cached_value("Swiss Wage Type", wage_type, "code")
	# //// Neoffice — was `== 1000`, see above.
	return cint(code) in BASE_SALARY_WAGE_TYPE_CODES


def _update_rate_based_components(doc, config, bases, ytd=None, period=None):
	"""Update components that are calculated as a percentage of their insurance base.

	Also adds missing component rows that may have been removed by remove_if_zero_valued
	during salary slip generation.

	//// Neoffice — LAA, LAAC and IJM no longer reduce to base x flat rate. Their
	//// amounts come from _insurance_solution_amounts(): the LAA insured salary is
	//// capped, the LAA code picks the business unit's rates and decides who pays the
	//// non-occupational premium, and the LAAC / IJM codes pick rates by category,
	//// wage bracket and sex. Every other component keeps base x rate.
	"""
	updated = False
	solution_amounts = _insurance_solution_amounts(doc, config, bases, ytd, period)
	existing_components = {row.salary_component for row in doc.get("deductions")}

	def expected_amount(comp_name, precision):
		if comp_name in solution_amounts:
			return solution_amounts[comp_name]
		rate_field, _is_employer, base_type = RATE_BASED_COMPONENTS[comp_name]
		rate = flt(config.get(rate_field))
		if not rate:
			return None
		# The base already reflects the prorated amounts paid, so the result is
		# final — prorating it again would double-count.
		base_amount = flt(bases.get(base_type, bases["gross_total"]))
		_record_base(doc, comp_name, base_amount, rate)
		# //// Neoffice — contributions round to 5 centimes (Swissdec guidelines 4.1.1:
		# //// "5er-Rundung"); they rounded to the centime. See rounding.py.
		return round_to_5_centimes(base_amount * rate / 100)

	managed = set(RATE_BASED_COMPONENTS) | set(solution_amounts)

	for row in doc.get("deductions"):
		if row.salary_component not in managed:
			continue
		amount = expected_amount(row.salary_component, row.precision("amount") or 2)
		if amount is None:
			continue
		if amount != flt(row.amount, row.precision("amount")):
			row.default_amount = amount
			row.amount = amount
			updated = True

	# Add missing components (removed by remove_if_zero_valued, or never in the structure)
	for comp_name in sorted(managed):
		if comp_name in existing_components:
			continue
		# //// Neoffice — prorate=False, and rounded like the loop above. The base is
		# //// built from the amounts ACTUALLY PAID, so it already carries the proration of a
		# //// partial month; _add_deduction_row used to apply payment_days/total_working_days
		# //// on top of it. An employee paid half the month had this contribution deducted at
		# //// a quarter — and only on the components the structure did not carry, so the same
		# //// slip mixed correct and quartered lines.
		amount = expected_amount(comp_name, 2)
		if amount:
			_add_deduction_row(doc, comp_name, amount, prorate=False)
			updated = True

	return updated


def _insurance_solution_amounts(doc, config, bases, ytd=None, period=None):
	"""LAA, LAAC and IJM amounts for this slip, per the Swissdec insurance solutions.

	LAA always goes through here, because its insured salary is capped at CHF 12'350
	a month whatever the configuration: the monthly slip never applied that cap, so
	above it the non-occupational premium was deducted on the whole salary. LAAC and
	IJM go through here only when the employee carries codes; otherwise they keep
	the flat rates. A code the configuration does not define stops the slip — a
	guessed rate would produce a payslip that is accepted and wrong.
	"""
	from hrms.regional.switzerland.insurance_solutions import (
		UnknownSolutionCode,
		compute_laa,
		compute_supplementary,
		laa_unit_rates,
		normalize_sex,
	)

	profile = _employee_insurance_profile(doc.employee)
	rows = _insurance_solution_rows(config)
	amounts = {}

	ytd = ytd or {}
	laa_base = flt(bases.get("laa_base", bases["gross_total"]))
	laa_cap = flt(config.get("laa_insurable_salary_cap")) or LAA_INSURABLE_SALARY_CAP
	# //// Neoffice — the LAA ceiling cumulated over the year (guidelines 7.12.3): capping each
	# //// month at 12'350 on its own made a 13th month paid in December lose the room of the
	# //// eleven months before it.
	laa_insured = (
		month_insured(ytd.get("laa"), period[0], laa_base, period[1], 0, laa_cap) if period else None
	)

	try:
		laa = compute_laa(
			laa_base,
			profile.get("ch_laa_code"),
			laa_unit_rates([r for r in rows if r.get("insurance") == "LAA"]),
			{
				"aap": flt(config.get("laa_professional_rate")),
				"aanp": flt(config.get("laa_nonprofessional_rate")),
			},
			annual_cap=laa_cap,
			insured_salary=laa_insured,
		)
		laa_rows = [r for r in rows if r.get("insurance") == "LAA"]
		laa_configured = bool(
			laa_rows
			or profile.get("ch_laa_code")
			or flt(config.get("laa_professional_rate"))
			or flt(config.get("laa_nonprofessional_rate"))
		)
		# A company with no LAA rate at all keeps whatever its salary structure
		# computes: taking over the components would zero them.
		if laa_configured:
			amounts["LAA Professional Employer"] = laa["aap_employer"]
			amounts["LAA Non-Professional Employee"] = laa["aanp_employee"]
			if laa["aanp_employer"]:
				amounts["LAA Non-Professional Employer"] = laa["aanp_employer"]
			# The insured salary is the CAPPED one, and the rates those of the employee's
			# business unit: neither can be read back from the flat configuration.
			for comp, rate in (
				("LAA Professional Employer", laa["rates"]["aap"]),
				("LAA Non-Professional Employee", laa["rates"]["aanp"]),
				("LAA Non-Professional Employer", laa["rates"]["aanp"]),
			):
				if amounts.get(comp):
					_record_base(doc, comp, laa["insured_salary"], rate)

		sex = normalize_sex(profile.get("gender"))
		for insurance, base_key, code_fields, components in (
			("LAAC", None, ("ch_laac_code", "ch_laac_code_2"), ("LAAC Employee", "LAAC Employer")),
			("IJM", "ijm_base", ("ch_ijm_code", "ch_ijm_code_2"), ("IJM/KTG Employee", "IJM/KTG Employer")),
		):
			# With codes, each bracket caps itself — and a LAAC "salary surplus" solution
			# exists precisely to cover what lies ABOVE the LAA ceiling, so it must see
			# the uncapped LAA-subject salary. (The flat LAAC below keeps the capped one.)
			base_key = base_key or "laa_base"
			base = flt(bases.get(base_key, bases["gross_total"]))
			ytd_key = "ijm" if insurance == "IJM" else "laa"
			result = compute_supplementary(
				base,
				[profile.get(f) for f in code_fields],
				[r for r in rows if r.get("insurance") == insurance],
				sex,
				# Each bracket cumulated over the year as well (guidelines 7.12.3).
				ytd_base=ytd.get(ytd_key) if period else None,
				days_before=period[0] if period else None,
				days_current=period[1] if period else None,
			)
			if result is None:
				if insurance == "LAAC":
					# Flat LAAC insures the LAA salary, so it carries the same cap.
					for comp, field in zip(
						components, ("laac_rate_employee", "laac_rate_employer"), strict=False
					):
						rate = flt(config.get(field))
						if rate:
							amounts[comp] = round_to_5_centimes(laa["insured_salary"] * rate / 100)
							_record_base(doc, comp, laa["insured_salary"], rate)
				continue
			amounts[components[0]] = result["employee"]
			amounts[components[1]] = result["employer"]
			# One bracket charged: its rate is THE rate. Several (brackets, two codes): no
			# single rate describes the amount, and printing one would be false.
			single = result["parts"][0] if len(result["parts"]) == 1 else None
			_record_base(
				doc, components[0], result["insured_salary"], single["rate_employee"] if single else ""
			)
			_record_base(
				doc, components[1], result["insured_salary"], single["rate_employer"] if single else ""
			)
			for warning in result["warnings"]:
				frappe.msgprint(_("{0}: {1}").format(insurance, warning), indicator="orange", alert=True)
	except UnknownSolutionCode as e:
		frappe.throw(
			_("Employee {0}: {1}").format(doc.employee, str(e)),
			title=_("Insurance code not configured"),
		)
	except ValueError as e:
		frappe.throw(
			_("Employee {0}: {1}").format(doc.employee, str(e)),
			title=_("Invalid insurance code"),
		)

	return amounts


_INSURANCE_PROFILE_FIELDS = (
	"gender",
	"ch_laa_code",
	"ch_laac_code",
	"ch_laac_code_2",
	"ch_ijm_code",
	"ch_ijm_code_2",
)


def _employee_insurance_profile(employee):
	"""The employee's sex and insurance codes — only the fields this site already has."""
	meta = frappe.get_meta("Employee")
	fields = [f for f in _INSURANCE_PROFILE_FIELDS if f == "gender" or meta.has_field(f)]
	return frappe.db.get_value("Employee", employee, fields, as_dict=True) or {}


def _insurance_solution_rows(config):
	"""The configuration's insurance-solution rows. The config is loaded with
	frappe.db.get_value, which never carries child tables, so they are read here."""
	if not config or not config.get("name") or not frappe.db.table_exists("Swiss Insurance Solution"):
		return []
	return frappe.get_all(
		"Swiss Insurance Solution",
		filters={
			"parent": config.get("name"),
			"parenttype": "Swiss Social Insurance Config",
			"parentfield": "insurance_solutions",
		},
		fields=[
			"insurance",
			"solution_code",
			"wage_from",
			"wage_to",
			"rate_employee_male",
			"rate_employer_male",
			"rate_employee_female",
			"rate_employer_female",
		],
		order_by="idx asc",
	)


def _update_ac_components(doc, config, ac_base, ytd=None, period=None, exempt=False):
	"""Update AC/ALV components under the ceiling cumulated pro rata temporis."""
	updated = False

	# //// Neoffice — was get_ytd_gross_for_employee (SUM of gross_pay). The ceiling was measuring
	# //// an AC-SUBJECT month against an ALL-EARNINGS year, so any earning that is not subject to
	# //// AC still pushed the employee towards the ceiling and cut the AC base of the month that
	# //// crosses it. See get_ytd_ac_base_for_employee for the worked example.
	if ytd is None:
		ytd = get_ytd_insurance_bases(doc.employee, doc.company, doc.start_date)
	if period is None:
		period = _contribution_period(doc, frappe.get_cached_doc("Employee", doc.employee), ytd)

	if exempt:
		# Youth, exempted or past the reference age: no AC at all this month.
		ac_result = {"ac_employee": 0.0, "ac_employer": 0.0, "subject_to_ac": 0.0}
	else:
		ac_result = calculate_ac_contribution(
			# //// Neoffice — second argument was ytd_gross; it is the AC-subject cumulative that
			# //// the ceiling is measured against, see get_ytd_insurance_bases. The days prorate
			# //// the ceiling (guidelines 7.12.3).
			ac_base,
			ytd.get("ac"),
			config,
			year=getdate(doc.end_date).year,
			days_before=period[0],
			days_current=period[1],
		)

	# Above the ceiling only part of the month is subject: that part is the base.
	for comp in ("AC/ALV Employee", "AC/ALV Employer"):
		_record_base(doc, comp, ac_result["subject_to_ac"])

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

	lpp_result = calculate_lpp_contribution(annual_salary, age, config, year=getdate(doc.end_date).year)

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

	# The base of LPP is the coordinated salary, not the earnings of the month.
	coordinated_monthly = flt(lpp_result.get("coordinated_salary")) / 12
	for row in doc.get("deductions"):
		if row.salary_component in lpp_mapping and flt(row.amount):
			_record_base(doc, row.salary_component, coordinated_monthly * _proration_factor(doc, row))

	return updated


def _proration_factor(doc, row):
	"""payment_days / total_working_days when the row is prorated, else 1."""
	if (
		cint(row.depends_on_payment_days)
		and cint(doc.total_working_days)
		and doc.payment_days != doc.total_working_days
	):
		return flt(doc.payment_days) / flt(doc.total_working_days)
	return 1.0


def _prorate_amount(doc, row, amount):
	"""Apply payment day proration to a component amount.

	Matches the standard Frappe HRMS behavior: when depends_on_payment_days
	is set and the employee has fewer payment days than total working days,
	the amount is prorated accordingly.
	"""
	factor = _proration_factor(doc, row)
	if factor != 1.0:
		# //// Neoffice — a prorated amount is a computed one: 5 centimes (Swissdec guidelines
		# //// 4.1.1), like the salary slip's own proration of a Swiss company's earnings.
		return round_to_5_centimes(amount * factor)
	return flt(amount, row.precision("amount"))


def _record_base(doc, component, base, rate=None):
	"""Remember the base, and the rate when it is not the configuration's, that a contribution
	of this slip was computed with. The payslip prints them.

	Reading them back from the amount (amount / rate) cannot work: once contributions round to
	5 centimes, 55.00 at 1.1 % reads back as 5'000.00 for a base of 5'001.10; a capped LAA or AC
	base is not the earnings of the month; and the LAA rate of a business unit or the LAAC rate
	of a code is not in the configuration's flat fields at all.

	rate=None leaves the payslip to the configuration's rate; "" says that no single rate
	describes the amount (several brackets or codes), so none is printed.
	"""
	record = doc.flags.get("ch_contribution_bases")
	if record is None:
		return
	entry = {"base": flt(base, 2)}
	if rate is not None:
		entry["rate"] = rate if rate == "" else flt(rate, 4)
	record[component] = entry


def _store_contribution_bases(doc):
	"""Write the bases recorded by this run on the slip, where the payslip reads them."""
	if doc.meta.has_field("ch_contribution_bases"):
		doc.ch_contribution_bases = json.dumps(doc.flags.get("ch_contribution_bases") or {}, sort_keys=True)


# //// Neoffice — upstream sets rounded_total = rounded(net_pay): to the whole FRANC. A Swiss
# //// payslip printed "Rounded Total CHF 5'016.00" and the amount in words of 5'016 while the
# //// payment file transferred the net pay, 5'016.45. The net is already rounded as Swiss
# //// payroll rounds (every computed amount to 5 centimes); it is what is paid, so it is what
# //// the slip states.
def _pay_the_net_as_computed(doc):
	"""rounded_total = net_pay on a Swiss slip, and the amount in words follows."""
	if cint(frappe.db.get_single_value("Payroll Settings", "disable_rounded_total")):
		return
	doc.rounded_total = flt(doc.net_pay, doc.precision("rounded_total"))
	doc.base_rounded_total = flt(doc.base_net_pay, doc.precision("base_rounded_total"))
	doc.set_net_total_in_words()


def _has_component(doc, component_name):
	"""Check if a salary component already exists in the slip deductions."""
	for row in doc.get("deductions"):
		if row.salary_component == component_name:
			return True
	return False


# //// Neoffice — prorate added. Proration is not idempotent: an amount computed on a base
# //// that is already prorated must be stored as it is. See the call in
# //// _update_rate_based_components.
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
	# //// Neoffice — see the prorate parameter above.
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


# //// Neoffice — restricted to the source-tax base with the imp_base fix below: the caller
# //// subtracts this total from that base to get the periodic part, so an aperiodic row that is
# //// NOT subject to source tax would make the periodic part too small — negative, even.
def _get_aperiodic_total(doc, config):
	"""Sum of the aperiodic earnings actually paid on this slip and subject to source tax."""
	thirteenth_mode = config.get("thirteenth_month_mode") or "Disabled"
	total = 0.0
	for row in doc.get("earnings"):
		if cint(row.get("do_not_include_in_total")):
			continue
		# //// Neoffice — see the note above the function: only the source-tax base counts here.
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
	# //// Neoffice — imp_base is passed on now. The caller computed it from the
	# //// ch_subject_to_imp flag of every component and this function dropped it:
	# //// calculate_source_tax summed ALL the earnings instead, so a component explicitly
	# //// marked as not subject to source tax was taxed like any other — and the tariff being
	# //// progressive, it also pushed the rate of everything else up.
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

	# The payslip prints base x rate only where that product IS the amount withheld: a monthly
	# slip with no correction. The annual model regularises the year to date and a correction
	# settles past months — a rate next to the base would not explain the amount there.
	rate_pct = flt(result.get("tax_rate")) * 100
	explained = (
		result.get("model") == "monthly"
		and not result.get("corrections")
		and round_to_5_centimes(flt(imp_base) * rate_pct / 100) == tax_amount
	)
	_record_base(doc, component, imp_base, rate_pct if explained else "")

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
		# //// Neoffice — prorate=False replaces the loop that used to undo the proration right
		# //// after _add_deduction_row applied it. Source tax is computed on the salary actually
		# //// paid and on the source-tax days of the period; it is never prorated again.
		_add_deduction_row(doc, component, tax_amount, prorate=False)
		updated = True

	return updated


def _recalculate_totals(doc):
	"""Recalculate salary slip totals after component amounts have been updated."""
	doc.gross_pay = doc.get_component_totals("earnings", depends_on_payment_days=1)
	doc.base_gross_pay = flt(flt(doc.gross_pay) * flt(doc.exchange_rate), doc.precision("base_gross_pay"))
	doc.set_net_pay()
	doc.compute_year_to_date()
	doc.compute_month_to_date()
