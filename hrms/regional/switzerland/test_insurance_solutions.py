# //// Neoffice — added file (no upstream equivalent): unit tests of the LAA / LAAC / IJM
# //// insurance-solution calculation.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Swissdec guidelines, section 7.4.2 (LAA) and 7.6.1 / 7.7 (LAAC, IJM).

LAA code: business unit (A-Z) + scope digit — 0 not insured, 1 occupational and
non-occupational with deduction, 2 same WITHOUT deduction (employer pays the
non-occupational premium), 3 occupational only (under 8 hours a week).
LAAC / IJM code: person group + category, rates by category, wage bracket and sex.
"""

import unittest

from hrms.regional.switzerland.insurance_solutions import (
	UnknownSolutionCode,
	compute_laa,
	compute_supplementary,
	normalize_sex,
	parse_laa_code,
	parse_solution_code,
)

FLAT = {"aap": 0.81, "aanp": 1.60}


def _row(code, ee_m, er_m, ee_f=0.0, er_f=0.0, wage_from=0.0, wage_to=0.0):
	return {
		"solution_code": code,
		"wage_from": wage_from,
		"wage_to": wage_to,
		"rate_employee_male": ee_m,
		"rate_employer_male": er_m,
		"rate_employee_female": ee_f,
		"rate_employer_female": er_f,
	}


class TestNormalizeSex(unittest.TestCase):
	def test_localised_values_all_resolve(self):
		"""This very instance stores 'Masculin' / 'Féminin' — the ELM needs M or F."""
		for value in ("Male", "Masculin", "männlich", "Maschile", "M", "masculin "):
			self.assertEqual(normalize_sex(value), "male", value)
		for value in ("Female", "Féminin", "weiblich", "Femminile", "F", "Feminin"):
			self.assertEqual(normalize_sex(value), "female", value)

	def test_other_or_empty_is_unknown(self):
		for value in ("Autre", "Other", "", None, "Prefer not to say"):
			self.assertIsNone(normalize_sex(value), value)


class TestParseCodes(unittest.TestCase):
	def test_laa_code(self):
		self.assertEqual(parse_laa_code("a1"), ("A", "1"))
		self.assertEqual(parse_laa_code(" B3 "), ("B", "3"))
		self.assertIsNone(parse_laa_code(""))

	def test_laa_code_scope_is_0_to_3(self):
		for bad in ("A4", "1A", "AA", "A", "A10"):
			with self.assertRaises(ValueError, msg=bad):
				parse_laa_code(bad)

	def test_supplementary_code_accepts_letters_and_digits(self):
		self.assertEqual(parse_solution_code("a1"), "A1")
		self.assertEqual(parse_solution_code("10"), "10")
		with self.assertRaises(ValueError):
			parse_solution_code("A")


class TestLaaFlat(unittest.TestCase):
	def test_ordinary_case_without_a_code(self):
		out = compute_laa(6000, None, {}, FLAT)
		self.assertEqual(out["insured_salary"], 6000)
		self.assertEqual(out["aap_employer"], 48.60)
		self.assertEqual(out["aanp_employee"], 96.00)
		self.assertEqual(out["aanp_employer"], 0.0)

	def test_monthly_cap_applies(self):
		"""CHF 148'200 a year is CHF 12'350 a month (guidelines 7.4.3)."""
		out = compute_laa(20000, None, {}, FLAT)
		self.assertEqual(out["insured_salary"], 12350)
		self.assertEqual(out["aanp_employee"], 197.60)  # not 320.00 on the whole salary
		self.assertEqual(out["aap_employer"], 100.04)

	def test_cap_scales_with_the_period(self):
		out = compute_laa(60000, None, {}, FLAT, months=3)
		self.assertEqual(out["insured_salary"], 37050)

	def test_a_custom_annual_cap(self):
		out = compute_laa(20000, None, {}, FLAT, annual_cap=120000)
		self.assertEqual(out["insured_salary"], 10000)


class TestLaaScope(unittest.TestCase):
	def test_scope_0_not_insured(self):
		out = compute_laa(6000, "A0", {}, FLAT)
		self.assertEqual((out["aap_employer"], out["aanp_employee"], out["aanp_employer"]), (0, 0, 0))

	def test_scope_2_employer_pays_the_non_occupational_premium(self):
		out = compute_laa(6000, "A2", {}, FLAT)
		self.assertEqual(out["aanp_employee"], 0.0)
		self.assertEqual(out["aanp_employer"], 96.00)
		self.assertEqual(out["aap_employer"], 48.60)

	def test_scope_3_occupational_only(self):
		"""Under 8 hours a week: not insured for non-occupational accidents at all."""
		out = compute_laa(2000, "A3", {}, FLAT)
		self.assertEqual(out["aanp_employee"], 0.0)
		self.assertEqual(out["aanp_employer"], 0.0)
		self.assertEqual(out["aap_employer"], 16.20)


class TestLaaBusinessUnits(unittest.TestCase):
	UNITS = {"A": {"aap": 0.1750, "aanp": 1.6060}, "B": {"aap": 0.3400, "aanp": 1.7010}}

	def test_each_unit_carries_its_own_rates(self):
		"""The guidelines' own example: unit A 0.1750 / 1.6060, unit B 0.3400 / 1.7010."""
		a = compute_laa(10000, "A1", self.UNITS, FLAT)
		b = compute_laa(10000, "B1", self.UNITS, FLAT)
		self.assertEqual((a["aap_employer"], a["aanp_employee"]), (17.50, 160.60))
		self.assertEqual((b["aap_employer"], b["aanp_employee"]), (34.00, 170.10))

	def test_an_unconfigured_unit_raises_rather_than_guessing(self):
		with self.assertRaises(UnknownSolutionCode):
			compute_laa(10000, "C1", self.UNITS, FLAT)

	def test_without_any_unit_row_the_flat_rates_are_the_unit_rates(self):
		out = compute_laa(6000, "A1", {}, FLAT)
		self.assertEqual(out["aanp_employee"], 96.00)


class TestSupplementary(unittest.TestCase):
	def test_no_code_returns_none_so_the_caller_keeps_the_flat_rates(self):
		self.assertIsNone(compute_supplementary(6000, [], [_row("A1", 0.3, 0.3)], "male"))

	def test_rates_by_sex(self):
		rows = [_row("A1", 0.30, 0.30, ee_f=0.50, er_f=0.50)]
		m = compute_supplementary(6000, ["A1"], rows, "male")
		f = compute_supplementary(6000, ["A1"], rows, "female")
		self.assertEqual((m["employee"], m["employer"]), (18.00, 18.00))
		self.assertEqual((f["employee"], f["employer"]), (30.00, 30.00))

	def test_an_empty_female_rate_means_the_insurer_does_not_differentiate(self):
		out = compute_supplementary(6000, ["A1"], [_row("A1", 0.30, 0.30)], "female")
		self.assertEqual(out["employee"], 18.00)

	def test_unknown_sex_with_differentiated_rates_warns(self):
		rows = [_row("A1", 0.30, 0.30, ee_f=0.50, er_f=0.50)]
		out = compute_supplementary(6000, ["A1"], rows, None)
		self.assertEqual(out["employee"], 18.00)
		self.assertTrue(out["warnings"])

	def test_unknown_sex_without_differentiation_is_silent(self):
		out = compute_supplementary(6000, ["A1"], [_row("A1", 0.30, 0.30)], None)
		self.assertEqual(out["warnings"], [])

	def test_a_bracket_above_the_laa_cap(self):
		"""Typical LAAC: covers the salary between CHF 148'200 and 300'000 a year."""
		rows = [_row("A2", 1.0, 1.0, wage_from=148200, wage_to=300000)]
		out = compute_supplementary(20000, ["A2"], rows, "male")
		self.assertEqual(out["insured_salary"], 7650)  # 20'000 - 12'350
		self.assertEqual(out["employee"], 76.50)

	def test_a_salary_under_the_bracket_pays_nothing(self):
		rows = [_row("A2", 1.0, 1.0, wage_from=148200, wage_to=300000)]
		out = compute_supplementary(6000, ["A2"], rows, "male")
		self.assertEqual(out["employee"], 0.0)

	def test_two_codes_cover_two_brackets(self):
		"""A person may carry at least two codes at once (guidelines 7.6.1)."""
		rows = [
			_row("A1", 0.50, 0.50, wage_from=0, wage_to=148200),
			_row("A2", 1.00, 1.00, wage_from=148200, wage_to=300000),
		]
		out = compute_supplementary(20000, ["A1", "A2"], rows, "male")
		self.assertEqual(out["insured_salary"], 20000)
		self.assertEqual(out["employee"], round(12350 * 0.005 + 7650 * 0.01, 2))

	def test_category_zero_without_a_row_means_not_insured(self):
		out = compute_supplementary(6000, ["A0"], [_row("A1", 0.3, 0.3)], "male")
		self.assertEqual((out["employee"], out["employer"]), (0.0, 0.0))

	def test_category_zero_can_be_overridden_by_a_row(self):
		"""The system must allow 0 to be given another meaning (guidelines 7.6.1)."""
		out = compute_supplementary(6000, ["A0"], [_row("A0", 0.2, 0.2)], "male")
		self.assertEqual(out["employee"], 12.00)

	def test_an_unknown_code_raises_rather_than_guessing(self):
		with self.assertRaises(UnknownSolutionCode):
			compute_supplementary(6000, ["Z9"], [_row("A1", 0.3, 0.3)], "male")
