#//// Neoffice — added file (no upstream equivalent): unit tests of the social-contribution helpers
#//// (AVS/AC/LPP/13th month). Sits next to the module it tests, unlike the fork-wide
#//// hrms/tests/test_utils.py.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest

from hrms.regional.switzerland.constants import (
	AC_ANNUAL_CEILING,
	LPP_COORDINATION_DEDUCTION,
	LPP_ENTRY_THRESHOLD,
	LPP_MAXIMUM_COORDINATED_SALARY,
	LPP_MINIMUM_INSURED_SALARY,
)
from hrms.regional.switzerland.utils import (
	_build_rate_dict,
	calculate_ac_contribution,
	calculate_lpp_contribution,
	calculate_lpp_coordinated_salary,
	calculate_thirteenth_month,
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
		# 50% split → employee: 1'593.90/year → 132.83/month
		self.assertEqual(result["coordinated_salary"], 45540)
		self.assertEqual(result["total_rate"], 0.07)
		self.assertAlmostEqual(result["employee_monthly"], 132.83, places=2)
		self.assertAlmostEqual(result["employer_monthly"], 132.83, places=2)

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
		# 50% split -> 4'819.50/year -> 401.625/month -> 401.63 (Swissdec commercial
		# rounding, half away from zero — proven by the Annex 1 oracle)
		self.assertEqual(result["coordinated_salary"], LPP_MAXIMUM_COORDINATED_SALARY)
		self.assertEqual(result["total_rate"], 0.15)
		self.assertAlmostEqual(result["employee_monthly"], 401.63, places=2)
		self.assertAlmostEqual(result["employer_monthly"], 401.63, places=2)

	def test_custom_employer_share(self):
		"""Custom employer share (60% employer, 40% employee)."""
		config = {"lpp_employer_share_pct": 60}
		result = calculate_lpp_contribution(72000, 30, config)
		# Coordinated: 45'540
		# Rate: 7%
		# Total annual: 3'187.80
		# 60% employer → 1'912.68/year → 159.39/month
		# 40% employee → 1'275.12/year → 106.26/month
		self.assertAlmostEqual(result["employer_monthly"], 159.39, places=2)
		self.assertAlmostEqual(result["employee_monthly"], 106.26, places=2)


class TestACContribution(unittest.TestCase):
	"""Tests for AC/ALV unemployment insurance contribution with ceiling tracking."""

	def test_below_ceiling(self):
		"""Standard case: YTD gross well below ceiling."""
		result = calculate_ac_contribution(8000, 40000)
		# Entire salary subject to AC at 1.1%
		self.assertAlmostEqual(result["ac_employee"], 88.0, places=2)  # 8000 * 0.011
		self.assertAlmostEqual(result["ac_employer"], 88.0, places=2)
		self.assertEqual(result["subject_to_ac"], 8000)
		self.assertEqual(result["exempt_above_ceiling"], 0)

	def test_above_ceiling(self):
		"""YTD already above ceiling: salary fully EXEMPT (solidarity abolished 2023)."""
		result = calculate_ac_contribution(8000, 150000)
		self.assertEqual(result["ac_employee"], 0)
		self.assertEqual(result["ac_employer"], 0)
		self.assertEqual(result["subject_to_ac"], 0)
		self.assertEqual(result["exempt_above_ceiling"], 8000)

	def test_ceiling_crossed_mid_month(self):
		"""Ceiling crossed during the current month: only the part below is subject."""
		# YTD = 145'000, monthly = 8'000, ceiling = 148'200
		# Subject to AC: 148'200 - 145'000 = 3'200 ; exempt: 4'800
		result = calculate_ac_contribution(8000, 145000)
		self.assertAlmostEqual(result["ac_employee"], 35.2, places=2)  # 3200 * 0.011
		self.assertAlmostEqual(result["ac_employer"], 35.2, places=2)
		self.assertEqual(result["subject_to_ac"], 3200)
		self.assertEqual(result["exempt_above_ceiling"], 4800)

	def test_exactly_at_ceiling(self):
		"""YTD + monthly exactly reaches the ceiling."""
		# YTD = 140'200, monthly = 8'000 → new YTD = 148'200
		result = calculate_ac_contribution(8000, 140200)
		# Entire salary subject to AC (exactly at ceiling)
		self.assertAlmostEqual(result["ac_employee"], 88.0, places=2)
		self.assertEqual(result["subject_to_ac"], 8000)
		self.assertEqual(result["exempt_above_ceiling"], 0)

	def test_first_month_of_year(self):
		"""First month: YTD is 0."""
		result = calculate_ac_contribution(8000, 0)
		self.assertAlmostEqual(result["ac_employee"], 88.0, places=2)
		self.assertEqual(result["exempt_above_ceiling"], 0)

	def test_zero_salary(self):
		"""Zero salary month (unpaid leave)."""
		result = calculate_ac_contribution(0, 80000)
		self.assertEqual(result["ac_employee"], 0)
		self.assertEqual(result["exempt_above_ceiling"], 0)


class TestThirteenthMonth(unittest.TestCase):
	"""Tests for 13th month salary calculation."""

	def test_disabled_mode(self):
		"""Mode Disabled: returns 0."""
		config = {"thirteenth_month_mode": "Disabled"}
		employee = {"date_of_joining": "2020-01-01", "relieving_date": None}
		result = calculate_thirteenth_month(8000, employee, "2025-12-01", "2025-12-31", config)
		self.assertEqual(result, 0)

	def test_monthly_mode(self):
		"""Monthly mode: returns base/12 regardless of month."""
		config = {"thirteenth_month_mode": "Monthly"}
		employee = {"date_of_joining": "2020-01-01", "relieving_date": None}
		result = calculate_thirteenth_month(6000, employee, "2025-06-01", "2025-06-30", config)
		self.assertAlmostEqual(result, 500.0, places=2)  # 6000 / 12

	def test_monthly_mode_any_month(self):
		"""Monthly mode: same amount in January and July."""
		config = {"thirteenth_month_mode": "Monthly"}
		employee = {"date_of_joining": "2020-01-01", "relieving_date": None}
		jan = calculate_thirteenth_month(8000, employee, "2025-01-01", "2025-01-31", config)
		jul = calculate_thirteenth_month(8000, employee, "2025-07-01", "2025-07-31", config)
		self.assertAlmostEqual(jan, 666.67, places=2)  # 8000 / 12
		self.assertEqual(jan, jul)

	def test_annual_mode_december_full_year(self):
		"""Annual mode, December: full year employee gets full base."""
		config = {"thirteenth_month_mode": "Annual"}
		employee = {"date_of_joining": "2020-01-01", "relieving_date": None}
		result = calculate_thirteenth_month(8000, employee, "2025-12-01", "2025-12-31", config)
		self.assertAlmostEqual(result, 8000.0, places=2)

	def test_annual_mode_not_december(self):
		"""Annual mode, not December and not leaving: returns 0."""
		config = {"thirteenth_month_mode": "Annual"}
		employee = {"date_of_joining": "2020-01-01", "relieving_date": None}
		result = calculate_thirteenth_month(8000, employee, "2025-06-01", "2025-06-30", config)
		self.assertEqual(result, 0)

	def test_annual_mode_prorata_hire(self):
		"""Annual mode, employee hired April 1: pro-rata based on days worked."""
		config = {"thirteenth_month_mode": "Annual"}
		employee = {"date_of_joining": "2025-04-01", "relieving_date": None}
		result = calculate_thirteenth_month(8000, employee, "2025-12-01", "2025-12-31", config)
		# April 1 to Dec 31 = 275 days out of 365
		expected = round(8000 * 275 / 365, 2)
		self.assertAlmostEqual(result, expected, places=2)

	def test_annual_mode_prorata_departure(self):
		"""Annual mode, employee leaving September 30: pro-rata on final slip."""
		config = {"thirteenth_month_mode": "Annual"}
		employee = {"date_of_joining": "2020-01-01", "relieving_date": "2025-09-30"}
		result = calculate_thirteenth_month(8000, employee, "2025-09-01", "2025-09-30", config)
		# Jan 1 to Sep 30 = 273 days out of 365
		expected = round(8000 * 273 / 365, 2)
		self.assertAlmostEqual(result, expected, places=2)

	def test_annual_mode_hired_december_15(self):
		"""Employee hired December 15: tiny pro-rata."""
		config = {"thirteenth_month_mode": "Annual"}
		employee = {"date_of_joining": "2025-12-15", "relieving_date": None}
		result = calculate_thirteenth_month(8000, employee, "2025-12-01", "2025-12-31", config)
		# Dec 15 to Dec 31 = 17 days out of 365
		expected = round(8000 * 17 / 365, 2)
		self.assertAlmostEqual(result, expected, places=2)

	def test_zero_base(self):
		"""Zero base salary: returns 0."""
		config = {"thirteenth_month_mode": "Monthly"}
		employee = {"date_of_joining": "2020-01-01", "relieving_date": None}
		result = calculate_thirteenth_month(0, employee, "2025-06-01", "2025-06-30", config)
		self.assertEqual(result, 0)

	def test_no_config(self):
		"""No config: returns 0."""
		employee = {"date_of_joining": "2020-01-01", "relieving_date": None}
		result = calculate_thirteenth_month(8000, employee, "2025-12-01", "2025-12-31", None)
		self.assertEqual(result, 0)


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

	def test_ac_ceiling_reached_before_december_thirteenth(self):
		"""AC ceiling already exceeded in November: December 13th month fully exempt.

		Employee CHF 14'000/month. By November end: YTD = 14'000x11 = 154'000 > 148'200.
		December gross = 14'000 (regular) + 14'000 (13th month) = 28'000.
		No AC at all above the ceiling (solidarity abolished 2023-01-01).
		"""
		december_gross = 28000  # regular + 13th month
		ytd_after_november = 14000 * 11  # 154'000

		result = calculate_ac_contribution(december_gross, ytd_after_november)

		self.assertEqual(result["subject_to_ac"], 0)
		self.assertEqual(result["ac_employee"], 0)
		self.assertEqual(result["ac_employer"], 0)
		self.assertEqual(result["exempt_above_ceiling"], 28000)


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
