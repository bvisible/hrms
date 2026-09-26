# //// Neoffice — added file (no upstream equivalent): unit tests of the social-contribution helpers
# //// (AVS/AC/LPP/13th month). Sits next to the module it tests, unlike the fork-wide
# //// hrms/tests/test_utils.py.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest
from unittest.mock import patch

import frappe

from hrms.regional.switzerland import extra_salaries
from hrms.regional.switzerland.constants import (
	AC_ANNUAL_CEILING,
	LPP_COORDINATION_DEDUCTION,
	LPP_ENTRY_THRESHOLD,
	LPP_MAXIMUM_COORDINATED_SALARY,
	LPP_MINIMUM_INSURED_SALARY,
)
from hrms.regional.switzerland.rounding import round_to_5_centimes
from hrms.regional.switzerland.utils import (
	_build_rate_dict,
	calculate_ac_contribution,
	calculate_lpp_contribution,
	calculate_lpp_coordinated_salary,
	get_employee_age,  # //// Neoffice — added with TestGetEmployeeAge at the end of the file.
	get_lpp_rate_for_age,
)


class TestLPPCoordinatedSalary(unittest.TestCase):
	"""Tests for LPP/BVG coordinated salary calculation."""

	def test_below_entry_threshold(self):
		"""Salary below CHF 22'680 is not insured."""
		result = calculate_lpp_coordinated_salary(20000)
		self.assertEqual(result, 0)

	def test_at_entry_threshold(self):
		"""Salary at exactly CHF 22'680 gets minimum insured salary."""
		result = calculate_lpp_coordinated_salary(LPP_ENTRY_THRESHOLD)
		# 22'680 - 26'460 = negative → capped at minimum 3'780
		self.assertEqual(result, LPP_MINIMUM_INSURED_SALARY)

	def test_minimum_insured_salary(self):
		"""Salary between entry threshold and coordination deduction yields minimum insured."""
		result = calculate_lpp_coordinated_salary(25000)
		# 25'000 - 26'460 = negative → capped at minimum 3'780
		self.assertEqual(result, LPP_MINIMUM_INSURED_SALARY)

	def test_normal_range(self):
		"""Salary in normal range: coordinated = salary - coordination deduction."""
		result = calculate_lpp_coordinated_salary(60000)
		expected = 60000 - LPP_COORDINATION_DEDUCTION  # 60'000 - 26'460 = 33'540
		self.assertEqual(result, expected)

	def test_above_maximum(self):
		"""Salary above maximum cap: coordinated salary capped at maximum."""
		result = calculate_lpp_coordinated_salary(150000)
		# 150'000 - 26'460 = 123'540 → capped at 64'260
		self.assertEqual(result, LPP_MAXIMUM_COORDINATED_SALARY)

	def test_exactly_at_coordination_deduction(self):
		"""Salary exactly at coordination deduction threshold."""
		result = calculate_lpp_coordinated_salary(LPP_COORDINATION_DEDUCTION)
		# 26'460 - 26'460 = 0 → below minimum → capped at 3'780
		self.assertEqual(result, LPP_MINIMUM_INSURED_SALARY)

	def test_maximum_boundary(self):
		"""Salary that yields exactly the maximum coordinated salary."""
		# Maximum coordinated = 64'260
		# salary - 26'460 = 64'260 → salary = 90'720
		result = calculate_lpp_coordinated_salary(90720)
		self.assertEqual(result, LPP_MAXIMUM_COORDINATED_SALARY)

	def test_just_above_maximum_boundary(self):
		"""Salary just above the boundary also gets maximum."""
		result = calculate_lpp_coordinated_salary(90721)
		self.assertEqual(result, LPP_MAXIMUM_COORDINATED_SALARY)


class TestLPPAgeRate(unittest.TestCase):
	"""Tests for LPP/BVG age bracket rate lookup."""

	def test_below_25(self):
		"""Below age 25: not insured under LPP minimum."""
		self.assertEqual(get_lpp_rate_for_age(24), 0)
		self.assertEqual(get_lpp_rate_for_age(20), 0)

	def test_age_25_to_34(self):
		"""Age 25-34: 7% rate."""
		self.assertEqual(get_lpp_rate_for_age(25), 0.07)
		self.assertEqual(get_lpp_rate_for_age(30), 0.07)
		self.assertEqual(get_lpp_rate_for_age(34), 0.07)

	def test_age_35_to_44(self):
		"""Age 35-44: 10% rate."""
		self.assertEqual(get_lpp_rate_for_age(35), 0.10)
		self.assertEqual(get_lpp_rate_for_age(40), 0.10)
		self.assertEqual(get_lpp_rate_for_age(44), 0.10)

	def test_age_45_to_54(self):
		"""Age 45-54: 15% rate."""
		self.assertEqual(get_lpp_rate_for_age(45), 0.15)
		self.assertEqual(get_lpp_rate_for_age(50), 0.15)
		self.assertEqual(get_lpp_rate_for_age(54), 0.15)

	def test_age_55_to_65(self):
		"""Age 55-65: 18% rate."""
		self.assertEqual(get_lpp_rate_for_age(55), 0.18)
		self.assertEqual(get_lpp_rate_for_age(60), 0.18)
		self.assertEqual(get_lpp_rate_for_age(65), 0.18)

	def test_above_65(self):
		"""Above age 65: not insured."""
		self.assertEqual(get_lpp_rate_for_age(66), 0)
		self.assertEqual(get_lpp_rate_for_age(70), 0)


class TestLPPContribution(unittest.TestCase):
	"""Tests for full LPP contribution calculation."""

	def test_normal_contribution_age_30(self):
		"""Age 30 with CHF 72'000 annual salary."""
		result = calculate_lpp_contribution(72000, 30)
		# Coordinated: 72'000 - 26'460 = 45'540
		# Rate: 7%
		# Total annual: 45'540 * 0.07 = 3'187.80
		# 50% split → employee: 1'593.90/year → 132.825/month → 132.85: contributions round
		# to 5 centimes (Swissdec guidelines 4.1.1, "5er-Rundung"), as a certified engine does.
		self.assertEqual(result["coordinated_salary"], 45540)
		self.assertEqual(result["total_rate"], 0.07)
		self.assertAlmostEqual(result["employee_monthly"], 132.85, places=2)
		self.assertAlmostEqual(result["employer_monthly"], 132.85, places=2)

	def test_below_threshold(self):
		"""Annual salary below entry threshold: no contribution."""
		result = calculate_lpp_contribution(20000, 30)
		self.assertEqual(result["coordinated_salary"], 0)
		self.assertEqual(result["employee_monthly"], 0)
		self.assertEqual(result["employer_monthly"], 0)

	def test_too_young(self):
		"""Below age 25: no LPP contribution."""
		result = calculate_lpp_contribution(72000, 23)
		self.assertEqual(result["total_rate"], 0)
		self.assertEqual(result["employee_monthly"], 0)
		self.assertEqual(result["employer_monthly"], 0)

	def test_age_50(self):
		"""Age 50 with high salary (above maximum coordinated)."""
		result = calculate_lpp_contribution(150000, 50)
		# Coordinated: capped at 64'260
		# Rate: 15% (age 45-54)
		# Total annual: 64'260 * 0.15 = 9'639.00
		# 50% split -> 4'819.50/year -> 401.625/month -> 401.65: contributions round to
		# 5 centimes, half away from zero (Swissdec guidelines 4.1.1). The centime rule of
		# the Annex 1 oracle is SOURCE TAX's, and stays there.
		self.assertEqual(result["coordinated_salary"], LPP_MAXIMUM_COORDINATED_SALARY)
		self.assertEqual(result["total_rate"], 0.15)
		self.assertAlmostEqual(result["employee_monthly"], 401.65, places=2)
		self.assertAlmostEqual(result["employer_monthly"], 401.65, places=2)

	def test_custom_employer_share(self):
		"""Custom employer share (60% employer, 40% employee)."""
		config = {"lpp_employer_share_pct": 60}
		result = calculate_lpp_contribution(72000, 30, config)
		# Coordinated: 45'540
		# Rate: 7%
		# Total annual: 3'187.80
		# 60% employer → 1'912.68/year → 159.39/month → 159.40 (5 centimes, guidelines 4.1.1)
		# 40% employee → 1'275.12/year → 106.26/month → 106.25
		self.assertAlmostEqual(result["employer_monthly"], 159.40, places=2)
		self.assertAlmostEqual(result["employee_monthly"], 106.25, places=2)


# //// Neoffice — LPP art. 33a, the last insured salary kept insured from 58 (2026-09-23).
class TestLPPMaintainedSalary(unittest.TestCase):
	def test_the_employee_pays_the_credits_on_the_difference(self):
		"""Cut from 120'000 to 72'000 at 60: 18 % on 45'540 shared, 18 % on the 18'720 above
		paid by the employee alone (art. 33a al. 3, no parity)."""
		result = calculate_lpp_contribution(72000, 60, maintained_salary=120000)
		self.assertEqual(result["coordinated_salary"], LPP_MAXIMUM_COORDINATED_SALARY)
		self.assertAlmostEqual(result["employer_monthly"], 341.55, places=2)  # 4'098.60 / 12
		self.assertAlmostEqual(result["employee_monthly"], 622.35, places=2)  # (4'098.60 + 3'369.60) / 12

	def test_an_employer_share_of_the_maintenance(self):
		result = calculate_lpp_contribution(72000, 60, maintained_salary=120000, maintained_employer_share=50)
		self.assertAlmostEqual(result["employer_monthly"], 481.95, places=2)
		self.assertAlmostEqual(result["employee_monthly"], 481.95, places=2)

	def test_a_maintained_salary_below_the_current_one_changes_nothing(self):
		self.assertEqual(
			calculate_lpp_contribution(72000, 60, maintained_salary=60000),
			calculate_lpp_contribution(72000, 60),
		)


class TestACContribution(unittest.TestCase):
	"""AC/ALV under the ceiling cumulated pro rata temporis (Swissdec guidelines 7.12.3).

	A full year of employment gives 12'350 of room a month (148'200 x 30 / 360). June is
	preceded by 150 days (room 61'750) and ends at 180 (room 74'100).
	"""

	def test_below_the_room(self):
		result = calculate_ac_contribution(8000, 40000, days_before=150, days_current=30)
		self.assertAlmostEqual(result["ac_employee"], 88.0, places=2)  # 8000 * 1.1%
		self.assertAlmostEqual(result["ac_employer"], 88.0, places=2)
		self.assertEqual(result["subject_to_ac"], 8000)
		self.assertEqual(result["exempt_above_ceiling"], 0)

	def test_the_room_runs_out_during_the_month(self):
		"""60'000 by May, 20'000 in June: 74'100 - 60'000 = 14'100 subject, 5'900 not."""
		result = calculate_ac_contribution(20000, 60000, days_before=150, days_current=30)
		self.assertEqual(result["subject_to_ac"], 14100)
		self.assertAlmostEqual(result["ac_employee"], 155.10, places=2)
		self.assertEqual(result["exempt_above_ceiling"], 5900)

	def test_exactly_at_the_room(self):
		result = calculate_ac_contribution(12350, 61750, days_before=150, days_current=30)
		self.assertEqual(result["subject_to_ac"], 12350)
		self.assertEqual(result["exempt_above_ceiling"], 0)

	def test_a_month_insures_what_earlier_months_could_not(self):
		"""May had 70'000 against 61'750 of room; June's 8'000 comes with 8'250 left over: the
		month insures 12'350 — 4'350 more than it pays. Negative 'exempt' says so."""
		result = calculate_ac_contribution(8000, 70000, days_before=150, days_current=30)
		self.assertEqual(result["subject_to_ac"], 12350)
		self.assertEqual(result["exempt_above_ceiling"], -4350)

	def test_a_payment_after_the_exit_once_the_room_is_used(self):
		"""Exit 30.06 with the six months' room filled: a bonus paid in July owes nothing."""
		result = calculate_ac_contribution(8000, 80000, days_before=180, days_current=0)
		self.assertEqual(result["ac_employee"], 0)
		self.assertEqual(result["subject_to_ac"], 0)
		self.assertEqual(result["exempt_above_ceiling"], 8000)

	def test_first_month_of_year(self):
		result = calculate_ac_contribution(8000, 0, days_before=0, days_current=30)
		self.assertAlmostEqual(result["ac_employee"], 88.0, places=2)
		self.assertEqual(result["exempt_above_ceiling"], 0)

	def test_a_month_without_salary_still_takes_up_the_backlog(self):
		"""80'000 by June against 74'100: July adds 12'350 of room, 5'900 of it is taken up."""
		result = calculate_ac_contribution(0, 80000, days_before=180, days_current=30)
		self.assertEqual(result["subject_to_ac"], 5900)
		self.assertAlmostEqual(result["ac_employee"], 64.90, places=2)

	def test_the_days_are_required(self):
		"""Without them no ceiling can be prorated: failing loudly beats the yearly shortcut."""
		with self.assertRaises(TypeError):
			calculate_ac_contribution(8000, 40000)


EMPLOYED = {"date_of_joining": "2020-01-01", "relieving_date": None}


class TestExtraSalaries(unittest.TestCase):
	"""The 13th, 14th and 15th salaries (extra_salaries.py): the base paid since the previous
	payment, divided by twelve; a month employed without a slip here counts the current base."""

	def slip(self, start, end, paid=8000, full=8000):
		row = frappe._dict(salary_component="Basic", abbr="B", amount=paid, default_amount=full)
		return frappe._dict(
			name="_T-slip", employee="_T-emp", company="_T-co", start_date=start, end_date=end, earnings=[row]
		)

	def compute(self, config, slip, employee, history=None):
		with patch.object(extra_salaries, "_base_paid_by_month", return_value=history or {}):
			return {r["extra_salary"]: r for r in extra_salaries.compute(slip, config, employee)}

	def test_none_without_an_extra_salary(self):
		self.assertEqual(
			extra_salaries.compute(
				self.slip("2025-12-01", "2025-12-31"), {"thirteenth_month_mode": "Disabled"}, EMPLOYED
			),
			[],
		)
		self.assertEqual(extra_salaries.compute(self.slip("2025-12-01", "2025-12-31"), None, EMPLOYED), [])

	def test_monthly_a_twelfth_of_the_base_paid(self):
		config = {"thirteenth_month_mode": "Monthly"}
		june = self.compute(config, self.slip("2025-06-01", "2025-06-30", 6000, 6000), EMPLOYED)
		self.assertEqual(june["13th"]["paid"], 500)
		# 8000 / 12 = 666.666... -> 666.65: a computed wage rounds to 5 centimes (guidelines 4.1.1)
		jan = self.compute(config, self.slip("2025-01-01", "2025-01-31"), EMPLOYED)
		self.assertEqual(jan["13th"]["paid"], 666.65)
		# A partial month pays a twelfth of what it paid, not of the full base.
		half = self.compute(config, self.slip("2025-01-01", "2025-01-31", 4000), EMPLOYED)
		self.assertEqual(half["13th"]["paid"], 333.35)

	def test_annual_in_december_the_year_employed(self):
		config = {"thirteenth_month_mode": "Annual"}
		december = self.compute(config, self.slip("2025-12-01", "2025-12-31"), EMPLOYED)
		self.assertEqual(december["13th"]["paid"], 8000)  # no slip here before: the current base
		june = self.compute(config, self.slip("2025-06-01", "2025-06-30"), EMPLOYED)
		self.assertEqual((june["13th"]["paid"], june["13th"]["accrued"]), (0, 666.67))

	def test_annual_counts_what_was_paid(self):
		"""An unpaid half-month in June: the 13th is short of it."""
		history = {(2025, m): 8000 for m in range(1, 12)}
		history[(2025, 6)] = 4000
		december = self.compute(
			{"thirteenth_month_mode": "Annual"}, self.slip("2025-12-01", "2025-12-31"), EMPLOYED, history
		)
		self.assertEqual(december["13th"]["paid"], round_to_5_centimes(92000 / 12))

	def test_the_salary_continued_during_a_paid_absence_counts(self):
		"""Half of March paid under illness (1301): the 13th is a twelfth of the whole 6'000, as the
		certified engine computes it; training pay (1303) stays out, as there (#837, 2026-09-26)."""
		codes = {"_T Monthly": "1000", "_T Illness": "1301", "_T Training": "1303"}
		slip = self.slip("2025-03-01", "2025-03-31")
		slip.earnings = [
			frappe._dict(salary_component=name, abbr="", amount=amount, default_amount=amount)
			for name, amount in (("_T Monthly", 3000), ("_T Illness", 3000), ("_T Training", 600))
		]

		def code_of(doctype, name, field):
			return codes[name]

		with patch.object(extra_salaries.frappe, "get_cached_value", code_of):
			march = self.compute({"thirteenth_month_mode": "Monthly"}, slip, EMPLOYED)
			# Annual: the months without a slip here count the whole current month, illness included.
			slip.start_date, slip.end_date = "2025-12-01", "2025-12-31"
			december = self.compute({"thirteenth_month_mode": "Annual"}, slip, EMPLOYED)
		self.assertEqual(march["13th"]["paid"], 500)
		self.assertEqual(december["13th"]["paid"], 6000)

	def test_annual_entry_and_exit_pro_rata(self):
		config = {"thirteenth_month_mode": "Annual"}
		hired = {"date_of_joining": "2025-04-01", "relieving_date": None}
		self.assertEqual(
			self.compute(config, self.slip("2025-12-01", "2025-12-31"), hired)["13th"]["paid"], 6000
		)
		leaving = {"date_of_joining": "2020-01-01", "relieving_date": "2025-09-30"}
		exit_month = self.compute(config, self.slip("2025-09-01", "2025-09-30"), leaving)
		self.assertEqual(exit_month["13th"]["paid"], 6000)  # January to September
		late = {"date_of_joining": "2025-12-15", "relieving_date": None}
		december = self.compute(config, self.slip("2025-12-01", "2025-12-31", 4387.10), late)
		self.assertEqual(december["13th"]["paid"], round_to_5_centimes(4387.10 / 12))

	def test_half_yearly_quarterly_and_a_14th_in_june(self):
		base = {(2025, m): 6000 for m in range(1, 6)}
		config = {"extra_salaries": [{"extra_salary": "13th", "percent": 100, "schedule": "Half-yearly"}]}
		june = self.compute(config, self.slip("2025-06-01", "2025-06-30", 6000, 6000), EMPLOYED, base)
		self.assertEqual(june["13th"]["paid"], 3000)
		config = {"extra_salaries": [{"extra_salary": "13th", "percent": 100, "schedule": "Quarterly"}]}
		march = self.compute(config, self.slip("2025-03-01", "2025-03-31", 6000, 6000), EMPLOYED, base)
		self.assertEqual(march["13th"]["paid"], 1500)
		config = {
			"extra_salaries": [
				{"extra_salary": "14th", "percent": 50, "schedule": "Annual", "payment_month": 6}
			]
		}
		history = {(2024, m): 6000 for m in range(7, 13)} | base
		june = self.compute(config, self.slip("2025-06-01", "2025-06-30", 6000, 6000), EMPLOYED, history)
		self.assertEqual(june["14th"]["paid"], 3000)  # July to June, half a month

	def test_accrual_periods(self):
		row = frappe._dict(schedule="Annual", payment_month=6)
		self.assertEqual(str(extra_salaries.accrual_start(row, "2025-05-01")), "2024-07-01")
		self.assertEqual(str(extra_salaries.accrual_start(row, "2025-08-01")), "2025-07-01")
		row = frappe._dict(schedule="Quarterly")
		self.assertEqual(str(extra_salaries.accrual_start(row, "2025-05-01")), "2025-04-01")
		row = frappe._dict(schedule="Annual", payment_month=12)
		self.assertEqual(str(extra_salaries.accrual_start(row, "2025-12-01")), "2025-01-01")

	def test_salaries_per_year_for_the_lpp(self):
		self.assertEqual(extra_salaries.salaries_per_year({"thirteenth_month_mode": "Annual"}), 13)
		self.assertEqual(extra_salaries.salaries_per_year({"thirteenth_month_mode": "Disabled"}), 12)
		config = {
			"extra_salaries": [
				{"extra_salary": "13th", "percent": 100, "schedule": "Annual"},
				{"extra_salary": "14th", "percent": 50, "schedule": "Annual"},
			]
		}
		self.assertEqual(extra_salaries.salaries_per_year(config), 13.5)


class TestThirteenthMonthIntegration(unittest.TestCase):
	"""Integration tests: 13th month interaction with LPP and AC."""

	def test_lpp_threshold_crossing_with_thirteenth(self):
		"""LPP entry threshold crossed only when annualizing with x13.

		Base CHF 1'800/month: 1'800x12 = 21'600 < 22'680 (below threshold).
		With 13th month: 1'800x13 = 23'400 > 22'680 (above threshold, LPP applies).
		"""
		annual_without_13 = 1800 * 12  # 21'600
		annual_with_13 = 1800 * 13  # 23'400

		result_without = calculate_lpp_contribution(annual_without_13, 30)
		result_with = calculate_lpp_contribution(annual_with_13, 30)

		# Without 13th month: below threshold, no LPP
		self.assertEqual(result_without["coordinated_salary"], 0)
		self.assertEqual(result_without["employee_monthly"], 0)

		# With 13th month: above threshold, LPP applies
		self.assertGreater(result_with["coordinated_salary"], 0)
		self.assertGreater(result_with["employee_monthly"], 0)
		# Coordinated salary = min(23'400 - 26'460, min_insured) = min(-3060, 3780) → 3'780
		self.assertEqual(result_with["coordinated_salary"], LPP_MINIMUM_INSURED_SALARY)

	def test_ac_in_december_with_the_13th_month(self):
		"""14'000 a month, 28'000 in December with the 13th month.

		Every month of the year insures 12'350, December included: 135.85. The old rule charged
		14'000 a month from January, reached the yearly 148'200 in November and exempted
		December altogether — same yearly total, months that were each wrong, and a leaver
		before December overcharged.
		"""
		december_gross = 28000  # regular + 13th month
		ytd_after_november = 14000 * 11  # 154'000, against 135'850 of room after 330 days

		result = calculate_ac_contribution(
			december_gross, ytd_after_november, days_before=330, days_current=30
		)

		self.assertEqual(result["subject_to_ac"], 12350)
		self.assertAlmostEqual(result["ac_employee"], 135.85, places=2)
		self.assertEqual(result["exempt_above_ceiling"], 28000 - 12350)


class TestComponentRates(unittest.TestCase):
	"""Tests for _build_rate_dict (pure function, no frappe needed)."""

	def _make_config(self, **overrides):
		"""Build a minimal config dict with defaults."""
		config = {
			"avs_rate_employee": 5.3,
			"avs_rate_employer": 5.3,
			"laa_professional_rate": 0.8,
			"laa_nonprofessional_rate": 1.2,
			"ijm_rate_employee": 0.5,
			"ijm_rate_employer": 0.5,
			"family_allowance_rate": 2.0,
			"ac_rate_employee": 1.1,
			"ac_rate_employer": 1.1,
			"ac_solidarity_rate_employee": 0.5,
			"ac_solidarity_rate_employer": 0.5,
			"lpp_employer_share_pct": 50,
		}
		config.update(overrides)
		return config

	def test_rate_based_components_have_rates(self):
		"""All rate-based components return their config rate."""
		config = self._make_config()
		rates = _build_rate_dict(config, 30)

		self.assertEqual(rates["AVS/AI/APG Employee"], "5.3")
		self.assertEqual(rates["AVS/AI/APG Employer"], "5.3")
		self.assertEqual(rates["LAA Professional Employer"], "0.8")
		self.assertEqual(rates["LAA Non-Professional Employee"], "1.2")
		self.assertEqual(rates["IJM/KTG Employee"], "0.5")
		self.assertEqual(rates["IJM/KTG Employer"], "0.5")
		self.assertEqual(rates["Family Allowances Employer"], "2.0")

	def test_ac_rates_included(self):
		"""AC standard rates are included; solidarity (abolished 2023) is not."""
		config = self._make_config()
		rates = _build_rate_dict(config, 30)

		self.assertEqual(rates["AC/ALV Employee"], "1.1")
		self.assertEqual(rates["AC/ALV Employer"], "1.1")
		self.assertNotIn("AC Solidarity Employee", rates)
		self.assertNotIn("AC Solidarity Employer", rates)

	def test_lpp_rate_age_30(self):
		"""LPP rate for age 30: 7% total, 50/50 split → 3.5% each."""
		config = self._make_config()
		rates = _build_rate_dict(config, 30)

		self.assertEqual(rates["LPP/BVG Employee"], "3.5")
		self.assertEqual(rates["LPP/BVG Employer"], "3.5")

	def test_lpp_rate_age_50(self):
		"""LPP rate for age 50: 15% total, 50/50 split → 7.5% each."""
		config = self._make_config()
		rates = _build_rate_dict(config, 50)

		self.assertEqual(rates["LPP/BVG Employee"], "7.5")
		self.assertEqual(rates["LPP/BVG Employer"], "7.5")

	def test_lpp_rate_custom_employer_share(self):
		"""LPP rate with 60% employer share: 7% total → EE 2.8%, ER 4.2%."""
		config = self._make_config(lpp_employer_share_pct=60)
		rates = _build_rate_dict(config, 30)

		self.assertEqual(rates["LPP/BVG Employee"], "2.8")
		self.assertEqual(rates["LPP/BVG Employer"], "4.2")

	def test_lpp_below_25_no_rate(self):
		"""Employee below 25: no LPP rate."""
		config = self._make_config()
		rates = _build_rate_dict(config, 24)

		self.assertNotIn("LPP/BVG Employee", rates)
		self.assertNotIn("LPP/BVG Employer", rates)

	def test_zero_rate_excluded(self):
		"""Components with 0% rate are excluded from the dict."""
		config = self._make_config(ijm_rate_employee=0, ijm_rate_employer=0)
		rates = _build_rate_dict(config, 30)

		self.assertNotIn("IJM/KTG Employee", rates)
		self.assertNotIn("IJM/KTG Employer", rates)

	def test_empty_config_returns_empty(self):
		"""Empty config returns empty dict (except LPP which uses constants)."""
		config = {}
		rates = _build_rate_dict(config, 30)

		# No rate-based components should appear
		self.assertNotIn("AVS/AI/APG Employee", rates)
		self.assertNotIn("AC/ALV Employee", rates)


if __name__ == "__main__":
	unittest.main()


class TestYearlyConstants(unittest.TestCase):
	"""Yearly vintages of the social insurance parameters."""

	def test_known_years(self):
		from hrms.regional.switzerland.constants import get_yearly_constants

		for year in (2025, 2026):
			yearly = get_yearly_constants(year)
			self.assertEqual(yearly["ac_annual_ceiling"], 148_200)
			self.assertEqual(yearly["lpp_coordination_deduction"], 26_460)

	def test_future_year_falls_back_to_latest(self):
		from unittest.mock import patch

		from hrms.regional.switzerland import constants

		with patch("frappe.log_error") as logged:
			yearly = constants.get_yearly_constants(2027)
		self.assertEqual(yearly, constants.YEARLY_CONSTANTS[2026])
		logged.assert_called_once()

	def test_year_flows_into_lpp(self):
		from hrms.regional.switzerland.utils import calculate_lpp_coordinated_salary

		# 90'000 gross, 2026 vintage: min(90'000, cap logic) - 26'460
		self.assertEqual(calculate_lpp_coordinated_salary(90_000, year=2026), 63_540)


BORN_1985 = {"date_of_birth": "1985-03-10"}


# //// Neoffice — tests of an added file (no upstream equivalent).
class TestGetEmployeeAge(unittest.TestCase):
	"""The BVG projection used to pass the year as an int; getdate() answers None to that."""

	def test_age_at_the_end_of_the_year(self):
		self.assertEqual(get_employee_age(BORN_1985, "2026-12-31"), 41)

	def test_age_before_the_birthday(self):
		self.assertEqual(get_employee_age(BORN_1985, "2026-01-31"), 40)

	def test_age_on_the_birthday(self):
		self.assertEqual(get_employee_age(BORN_1985, "2026-03-10"), 41)

	def test_no_date_of_birth(self):
		self.assertEqual(get_employee_age({}, "2026-12-31"), 0)

	def test_an_unusable_reference_date_says_so(self):
		"""An int year used to reach reference_date.year as None: AttributeError, pointing at
		the wrong line. It names the value it was given now."""
		with self.assertRaises(ValueError):
			get_employee_age(BORN_1985, 2026)
