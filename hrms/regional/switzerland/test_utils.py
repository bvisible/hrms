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
	calculate_ac_contribution,
	calculate_lpp_contribution,
	calculate_lpp_coordinated_salary,
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
		# 50% split → 4'819.50/year → 401.63/month
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
		self.assertEqual(result["solidarity_employee"], 0)
		self.assertEqual(result["solidarity_employer"], 0)
		self.assertEqual(result["subject_to_ac"], 8000)
		self.assertEqual(result["subject_to_solidarity"], 0)

	def test_above_ceiling(self):
		"""YTD already above ceiling: solidarity rate applies."""
		result = calculate_ac_contribution(8000, 150000)
		# Already above ceiling: entire salary subject to solidarity
		self.assertEqual(result["ac_employee"], 0)
		self.assertEqual(result["ac_employer"], 0)
		self.assertAlmostEqual(result["solidarity_employee"], 40.0, places=2)  # 8000 * 0.005
		self.assertAlmostEqual(result["solidarity_employer"], 40.0, places=2)
		self.assertEqual(result["subject_to_ac"], 0)
		self.assertEqual(result["subject_to_solidarity"], 8000)

	def test_ceiling_crossed_mid_month(self):
		"""Ceiling crossed during the current month: split calculation."""
		# YTD = 145'000, monthly = 8'000, ceiling = 148'200
		# Subject to AC: 148'200 - 145'000 = 3'200
		# Subject to solidarity: 8'000 - 3'200 = 4'800
		result = calculate_ac_contribution(8000, 145000)
		self.assertAlmostEqual(result["ac_employee"], 35.2, places=2)  # 3200 * 0.011
		self.assertAlmostEqual(result["ac_employer"], 35.2, places=2)
		self.assertAlmostEqual(result["solidarity_employee"], 24.0, places=2)  # 4800 * 0.005
		self.assertAlmostEqual(result["solidarity_employer"], 24.0, places=2)
		self.assertEqual(result["subject_to_ac"], 3200)
		self.assertEqual(result["subject_to_solidarity"], 4800)

	def test_exactly_at_ceiling(self):
		"""YTD + monthly exactly reaches the ceiling."""
		# YTD = 140'200, monthly = 8'000 → new YTD = 148'200
		result = calculate_ac_contribution(8000, 140200)
		# Entire salary subject to AC (exactly at ceiling)
		self.assertAlmostEqual(result["ac_employee"], 88.0, places=2)
		self.assertEqual(result["solidarity_employee"], 0)
		self.assertEqual(result["subject_to_ac"], 8000)
		self.assertEqual(result["subject_to_solidarity"], 0)

	def test_first_month_of_year(self):
		"""First month: YTD is 0."""
		result = calculate_ac_contribution(8000, 0)
		self.assertAlmostEqual(result["ac_employee"], 88.0, places=2)
		self.assertEqual(result["solidarity_employee"], 0)

	def test_zero_salary(self):
		"""Zero salary month (unpaid leave)."""
		result = calculate_ac_contribution(0, 80000)
		self.assertEqual(result["ac_employee"], 0)
		self.assertEqual(result["solidarity_employee"], 0)


if __name__ == "__main__":
	unittest.main()
