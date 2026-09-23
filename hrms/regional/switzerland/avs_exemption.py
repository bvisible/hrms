# //// Neoffice — added file (no upstream equivalent): AVS liability by age and status.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""AVS/AC liability rules that depend on the employee's age and status.

Two cases are not covered by a flat rate on the gross, and both are common:

* **Under the contribution start age.** Liability to AVS/AI/APG begins on
  1 January following the 17th birthday (OFAS leaflet 2.01). An apprentice below
  that age pays neither AVS nor AC — only LAA applies from day one.

* **Working past the reference age.** AVS is then due only on the part of the
  income ABOVE an exemption of CHF 1'400 per month (CHF 16'800 per year),
  granted *per employment relationship*. Since the AVS 21 reform the employee
  may waive it in order to earn a higher pension: the waiver is a declared
  status. And from the reference age there is no unemployment cover at all, so
  **no AC contribution is due either** (art. 2 al. 2 let. c LACI) — in both the
  exempted and the waived case.

Both ends are read from the birth date and the sex whenever nothing was declared: AVS
liability "must always be determined from the date of birth and the sex" (Swissdec
guidelines 6.0, 8.1.1, translated). A declared status still wins, for what no birth date
says (the waiver, another exemption).

Everything here is a pure function: no frappe import, no database, so the rules
can be tested on their own against the Swissdec oracle.
"""

from datetime import date

from hrms.regional.switzerland.constants import (
	AVS_STATUS_EXEMPTED,
	AVS_STATUS_RETIRED,
	AVS_STATUS_RETIRED_WAIVED,
	AVS_STATUS_YOUTH,
	get_yearly_constants,
)
from hrms.regional.switzerland.insurance_solutions import SEX_FEMALE, SEX_MALE

# AVS 21 transition (LAVS art. 21 and its transitional provisions, Swissdec guidelines 8.1.1):
# women born in 1961, 1962 and 1963 reach the reference age at 64 years and 3, 6 and 9 months.
_WOMEN_REFERENCE_AGE_MONTHS = {1961: 64 * 12 + 3, 1962: 64 * 12 + 6, 1963: 64 * 12 + 9}


def age_in_year(birth_date, year):
	"""The age reached in ``year``: the calendar year minus the year of birth.

	Liability to AVS starts on 1 January of the year of the 18th birthday — born 7.8.2003,
	liable from 1.1.2021, in the example of the guidelines (8.1.1) — and the LPP age that sets
	the savings credit is the calendar year minus the year of birth too.
	Neither waits for the birthday: an age counted to the day made an apprentice born in
	November a minor for ten months of the year he was liable in.
	"""
	return int(year) - birth_date.year


def reference_age_months(birth_date, sex):
	"""The AVS reference age of this person, in months; None when the sex is not known."""
	if sex == SEX_MALE:
		return 65 * 12
	if sex == SEX_FEMALE:
		if birth_date.year <= 1960:
			return 64 * 12
		return _WOMEN_REFERENCE_AGE_MONTHS.get(birth_date.year, 65 * 12)
	return None


def retirement_start(birth_date, sex):
	"""First day of the month after the one in which the reference age is reached.

	From that day AC is no longer due and the pensioner's AVS exemption applies: those who
	reached the AVS reference age are released "from the following month" (guidelines 8.1.1,
	translated). None when the sex is not known.
	"""
	months = reference_age_months(birth_date, sex)
	if months is None:
		return None
	month_index = birth_date.year * 12 + birth_date.month - 1 + months + 1
	return date(month_index // 12, month_index % 12 + 1, 1)


def is_past_reference_age(birth_date, sex, period_start):
	"""Whether a period starting on ``period_start`` falls after the reference age."""
	if not birth_date or not period_start:
		return False
	start = retirement_start(birth_date, sex)
	return bool(start and period_start >= start)


def resolve_avs_status(declared_status, age, year=None, past_reference_age=False):
	"""The status actually to apply, from what was declared, the age and the reference age.

	A declared status always wins: it carries a decision (waiving the exemption,
	an exemption granted for another reason) that no birth date can express. With
	nothing declared, the birth date decides both ends of the working life.

	Args:
		age: the age reached during the year (``age_in_year``), not the age to the day.
		past_reference_age: the period falls after the reference age (``is_past_reference_age``).
	"""
	declared = (declared_status or "").strip()
	if declared:
		return declared
	start_age = get_yearly_constants(year)["avs_contribution_start_age"] if year else 18
	if age is not None and age < start_age:
		return AVS_STATUS_YOUTH
	if past_reference_age:
		return AVS_STATUS_RETIRED
	return ""


def apply_avs_status(avs_base, ac_base, status, months=1, year=None):
	"""Adjust the AVS and AC bases for the employee's status.

	Args:
		avs_base: AVS base before any exemption.
		ac_base: AC base before any exemption.
		status: one of constants.AVS_STATUSES; anything falsy means full liability.
		months: number of months the bases cover — the exemption is monthly, so a
			quarterly or yearly run must not deduct a single month's worth.
		year: vintage to read the exemption from; the latest is used if omitted.

	Returns:
		dict with the adjusted ``avs_base`` and ``ac_base``, the ``exemption``
		actually deducted, and the ``status`` that was applied.
	"""
	status = (status or "").strip()
	avs_base = float(avs_base or 0)
	ac_base = float(ac_base or 0)
	result = {"avs_base": avs_base, "ac_base": ac_base, "exemption": 0.0, "status": status}

	if status in (AVS_STATUS_YOUTH, AVS_STATUS_EXEMPTED):
		# Neither AVS/AI/APG nor AC is due.
		result["avs_base"] = 0.0
		result["ac_base"] = 0.0
		return result

	if status in (AVS_STATUS_RETIRED, AVS_STATUS_RETIRED_WAIVED):
		# Past the reference age there is no unemployment cover, in both cases.
		result["ac_base"] = 0.0
		if status == AVS_STATUS_RETIRED:
			monthly = get_yearly_constants(year)["avs_retirement_exemption_monthly"]
			exemption = min(avs_base, monthly * max(int(months or 1), 1))
			result["exemption"] = round(exemption, 2)
			result["avs_base"] = round(avs_base - exemption, 2)
		return result

	return result
