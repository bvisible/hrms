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
  may waive it in order to earn a higher pension, so this is a declared status,
  never something inferred from the birth date alone. And from the reference age
  there is no unemployment cover at all, so **no AC contribution is due either**
  (art. 2 al. 2 let. c LACI) — in both the exempted and the waived case.

Everything here is a pure function: no frappe import, no database, so the rules
can be tested on their own against the Swissdec oracle.
"""

from hrms.regional.switzerland.constants import (
	AVS_STATUS_EXEMPTED,
	AVS_STATUS_RETIRED,
	AVS_STATUS_RETIRED_WAIVED,
	AVS_STATUS_YOUTH,
	get_yearly_constants,
)


def resolve_avs_status(declared_status, age, year=None):
	"""The status actually to apply, from what was declared and the employee's age.

	A declared status always wins: it carries a decision (waiving the exemption,
	an exemption granted for another reason) that no birth date can express. Age
	is only consulted to catch the under-age case when nothing was declared.
	"""
	declared = (declared_status or "").strip()
	if declared:
		return declared
	start_age = get_yearly_constants(year)["avs_contribution_start_age"] if year else 18
	if age is not None and age < start_age:
		return AVS_STATUS_YOUTH
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
