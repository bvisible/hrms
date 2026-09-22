# //// Neoffice — added file (no upstream equivalent): LAA / LAAC / IJM contributions per
# //// insurance solution, as the Swissdec guidelines model them.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""LAA, LAAC and IJM contributions, computed per insurance solution.

Until now each company had ONE flat rate per insurance, applied to the whole
salary. The Swissdec guidelines model something richer, and the difference
changes what is deducted, not just what is declared:

LAA (section 7.4.2) — a two-character code per employee:
  * the first character is the **business unit** (A-Z) the insurer assigns, and
    each unit carries its own rates (the guidelines' example: unit A
    AAP 0.1750 % / AANP 1.6060 %, unit B 0.3400 % / 1.7010 %);
  * the second is the **scope** of cover: 0 not insured, 1 occupational and
    non-occupational WITH the non-occupational premium deducted, 2 the same
    WITHOUT deduction — the employer pays it — and 3 occupational only, for
    someone working under 8 hours a week, who is not insured for
    non-occupational accidents at all.
  The insured salary is capped at CHF 148'200 a year, or CHF 12'350 a month
  (section 7.4.3 allows either). The monthly slip never applied that cap: above
  it, the non-occupational premium was deducted on the whole salary.
  The LAA rates differ by business unit, NOT by sex — the guidelines show no sex
  column for LAA. (A certified competitor offers one anyway; it is a
  generalisation, not the standard.)

LAAC and IJM (sections 7.6.1 and 7.7) — a two-character code per employee too:
  a person group (A-Z or 0-9) and an insurance category. Rates differ by
  category, by **wage bracket** and by **sex** ("% Männer / % Frauen"), and a
  person can hold **at least two** codes at once, typically one for the salary up
  to the LAA cap and one for the salary above it. Category 0 is reserved for
  "belongs to the group but not insured" — and the system must still let a
  company give 0 another meaning.

Everything here is pure: no frappe, no database, so the rules are tested alone.
Unknown codes raise instead of falling back to a guess — a wrong rate yields a
payslip that is accepted and wrong.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

from hrms.regional.switzerland.ceilings import month_insured
from hrms.regional.switzerland.constants import LAA_INSURABLE_SALARY_CAP
from hrms.regional.switzerland.rounding import round_to_5_centimes

SEX_MALE = "male"
SEX_FEMALE = "female"

# Gender records are free text in Frappe and localised per instance: one site
# stores "Masculin" / "Féminin", another "Male" / "Female". The ELM only knows
# M and F, and the LAAC / IJM rates only male and female.
_FEMALE_VALUES = frozenset(
	{
		"female",
		"féminin",
		"feminin",
		"femme",
		"f",
		"weiblich",
		"frau",
		"w",
		"femminile",
		"donna",
	}
)
_MALE_VALUES = frozenset(
	{
		"male",
		"masculin",
		"homme",
		"m",
		"männlich",
		"maennlich",
		"mann",
		"maschile",
		"uomo",
	}
)

LAA_SCOPE_NOT_INSURED = "0"
LAA_SCOPE_WITH_DEDUCTION = "1"
LAA_SCOPE_EMPLOYER_PAYS_AANP = "2"
LAA_SCOPE_OCCUPATIONAL_ONLY = "3"

_LAA_CODE = re.compile(r"[A-Z][0-3]")
_SOLUTION_CODE = re.compile(r"[A-Z0-9]{2}")
_CENT = Decimal("0.01")


class UnknownSolutionCode(ValueError):
	"""An employee carries a code the company's configuration does not define."""


def normalize_sex(value):
	"""'male', 'female', or None when the record does not say (e.g. 'Autre')."""
	v = (value or "").strip().lower()
	if v in _FEMALE_VALUES:
		return SEX_FEMALE
	if v in _MALE_VALUES:
		return SEX_MALE
	return None


def parse_laa_code(code):
	"""'A1' -> ('A', '1'); None for an empty code; ValueError when malformed."""
	c = (code or "").strip().upper()
	if not c:
		return None
	if not _LAA_CODE.fullmatch(c):
		raise ValueError(
			f"LAA code {code!r} is malformed: expected a business unit letter A-Z followed by "
			"the scope 0 (not insured), 1 (with deduction), 2 (without deduction) or "
			"3 (occupational only, under 8 hours a week)."
		)
	return c[0], c[1]


def parse_solution_code(code):
	"""Normalised two-character LAAC / IJM code, None when empty, ValueError otherwise."""
	c = (code or "").strip().upper()
	if not c:
		return None
	if not _SOLUTION_CODE.fullmatch(c):
		raise ValueError(
			f"Insurance code {code!r} is malformed: expected two characters, a person group "
			"(A-Z or 0-9) and a category."
		)
	return c


def laa_unit_rates(rows):
	"""{unit: {"aap": %, "aanp": %}} from the LAA solution rows of a configuration.

	The employer columns carry the occupational premium (always the employer's),
	the employee columns the non-occupational one.
	"""
	units = {}
	for row in rows or []:
		unit = (row.get("solution_code") or "").strip().upper()
		if unit:
			units[unit] = {
				"aap": float(row.get("rate_employer_male") or 0),
				"aanp": float(row.get("rate_employee_male") or 0),
			}
	return units


def compute_laa(base, code, unit_rates, flat_rates, annual_cap=None, months=1, insured_salary=None):
	"""LAA contributions for one employee over ``months`` months.

	Args:
		base: LAA-subject earnings of the period.
		code: the employee's LAA code ("A1"), or None for the ordinary case.
		unit_rates: {unit: {"aap": %, "aanp": %}} — may be empty.
		flat_rates: {"aap": %, "aanp": %} from the configuration's flat fields; they
			ARE the unit's rates when no unit is configured.
		annual_cap: insured-salary ceiling per year (default: the legal one).
		months: months covered — the cap is monthly, so a quarter gets three.
		insured_salary: the insured wage when the caller already applied the ceiling, as
			guidelines 7.12.3 want it — cumulated over the year (see ceilings.py). ``base``
			and the monthly cap are then ignored.

	Returns:
		dict with insured_salary, aap_employer, aanp_employee, aanp_employer, unit, scope,
		and rates — the {"aap", "aanp"} percentages applied, which the payslip prints.
	"""
	if insured_salary is not None:
		insured = Decimal(str(insured_salary))
	else:
		cap = Decimal(str(annual_cap or LAA_INSURABLE_SALARY_CAP)) / 12 * max(int(months or 1), 1)
		insured = min(max(Decimal(str(base or 0)), Decimal(0)), cap)

	parsed = parse_laa_code(code) if code else None
	if parsed:
		unit, scope = parsed
		if unit_rates:
			if unit not in unit_rates:
				raise UnknownSolutionCode(
					f"LAA business unit {unit!r} (code {code}) has no rates in the insurance "
					f"configuration; configured units: {', '.join(sorted(unit_rates))}."
				)
			rates = unit_rates[unit]
		else:
			rates = flat_rates
	else:
		unit, scope, rates = None, LAA_SCOPE_WITH_DEDUCTION, flat_rates

	zero = {
		"insured_salary": 0.0,
		"aap_employer": 0.0,
		"aanp_employee": 0.0,
		"aanp_employer": 0.0,
		"unit": unit,
		"scope": scope,
		"rates": {"aap": float(rates.get("aap") or 0), "aanp": float(rates.get("aanp") or 0)},
	}
	if scope == LAA_SCOPE_NOT_INSURED:
		return zero

	aap = _pct(insured, rates.get("aap"))
	aanp = _pct(insured, rates.get("aanp"))
	result = dict(zero, insured_salary=_money(insured), aap_employer=round_to_5_centimes(aap))
	if scope == LAA_SCOPE_WITH_DEDUCTION:
		result["aanp_employee"] = round_to_5_centimes(aanp)
	elif scope == LAA_SCOPE_EMPLOYER_PAYS_AANP:
		result["aanp_employer"] = round_to_5_centimes(aanp)
	# LAA_SCOPE_OCCUPATIONAL_ONLY: no non-occupational cover, nothing to charge.
	return result


def compute_supplementary(
	base, codes, rows, sex, months=1, ytd_base=None, days_before=None, days_current=None
):
	"""LAAC or IJM contributions for one employee — one insurance at a time.

	Args:
		base: subject earnings of the period.
		codes: the employee's codes for this insurance (up to two are usual).
		rows: the configuration's solution rows for THIS insurance. ``wage_from`` and
			``wage_to`` are YEARLY bounds, as insurers publish them; a zero
			``wage_to`` means no upper bound.
		sex: 'male', 'female' or None.
		months: months covered — brackets scale with the period.
		ytd_base, days_before, days_current: when given, each bracket is applied the way
			guidelines 7.12.3 want it — to the base cumulated over the year against the
			bracket prorated to the contribution days (see ceilings.py). ``months`` is then
			ignored.

	Returns:
		None when the employee has no code (the caller keeps the flat rates),
		otherwise a dict with employee, employer, insured_salary, codes, warnings, and
		parts — one {code, insured, rate_employee, rate_employer} per bracket charged.
	"""
	parsed = [c for c in (parse_solution_code(c) for c in (codes or [])) if c]
	if not parsed:
		return None

	by_code = {}
	for row in rows or []:
		c = parse_solution_code(row.get("solution_code"))
		if c:
			by_code.setdefault(c, []).append(row)

	months = max(int(months or 1), 1)
	amount = Decimal(str(base or 0))
	cumulated = days_current is not None
	employee = employer = insured = Decimal(0)
	warnings = []
	parts = []

	for code in parsed:
		code_rows = by_code.get(code)
		if not code_rows:
			if code[1] == "0":
				continue  # category 0: in the group, but not insured
			raise UnknownSolutionCode(
				f"Insurance code {code} has no rates in the insurance configuration; "
				f"configured codes: {', '.join(sorted(by_code)) or 'none'}."
			)
		for row in code_rows:
			if cumulated:
				part = Decimal(
					str(
						month_insured(
							ytd_base,
							days_before,
							base,
							days_current,
							row.get("wage_from") or 0,
							row.get("wage_to") or None,
						)
					)
				)
			else:
				low = Decimal(str(row.get("wage_from") or 0)) / 12 * months
				top = Decimal(str(row.get("wage_to") or 0))
				high = top / 12 * months if top else None
				ceiling = amount if high is None else min(amount, high)
				part = max(ceiling - low, Decimal(0))
			ee_rate, er_rate, ambiguous = _rates_for(row, sex)
			if ambiguous:
				warnings.append(
					f"code {code}: the insurer charges men and women differently but the "
					"employee's sex is not recorded as male or female — the male rate was used."
				)
			employee += _pct(part, ee_rate)
			employer += _pct(part, er_rate)
			insured += part
			if part:
				parts.append(
					{
						"code": code,
						"insured": _money(part),
						"rate_employee": ee_rate,
						"rate_employer": er_rate,
					}
				)

	return {
		# Contributions: 5 centimes (Swissdec guidelines 4.1.1); the salary: the centime.
		"employee": round_to_5_centimes(employee),
		"employer": round_to_5_centimes(employer),
		"insured_salary": _money(insured),
		"codes": parsed,
		"warnings": warnings,
		"parts": parts,
	}


def _rates_for(row, sex):
	"""(employee %, employer %, ambiguous?) for this row and this sex.

	An empty female rate means the insurer does not differentiate: it falls back
	to the male one. A genuinely zero rate for women only, with a non-zero rate for
	men, is not something any insurer publishes.
	"""
	m_ee = float(row.get("rate_employee_male") or 0)
	m_er = float(row.get("rate_employer_male") or 0)
	f_ee = float(row.get("rate_employee_female") or 0) or m_ee
	f_er = float(row.get("rate_employer_female") or 0) or m_er
	if sex == SEX_FEMALE:
		return f_ee, f_er, False
	if sex == SEX_MALE:
		return m_ee, m_er, False
	return m_ee, m_er, (f_ee, f_er) != (m_ee, m_er)


def _pct(amount, rate):
	return Decimal(str(amount)) * Decimal(str(rate or 0)) / Decimal(100)


def _money(value):
	"""A salary amount, to the centime. Contributions go through round_to_5_centimes."""
	return float(Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP))
