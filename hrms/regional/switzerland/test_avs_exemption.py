# //// Neoffice — added file (no upstream equivalent): unit tests of the AVS liability rules.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest
from datetime import date

from hrms.regional.switzerland.avs_exemption import (
	age_in_year,
	apply_avs_status,
	is_past_reference_age,
	reference_age_months,
	resolve_avs_status,
	retirement_start,
)
from hrms.regional.switzerland.constants import (
	AVS_RETIREMENT_EXEMPTION_MONTHLY,
	AVS_STATUS_EXEMPTED,
	AVS_STATUS_RETIRED,
	AVS_STATUS_RETIRED_WAIVED,
	AVS_STATUS_YOUTH,
)


class TestResolveAvsStatus(unittest.TestCase):
	def test_declared_status_wins_over_age(self):
		"""A declared status carries a decision no birth date can express."""
		self.assertEqual(resolve_avs_status(AVS_STATUS_RETIRED_WAIVED, age=70), AVS_STATUS_RETIRED_WAIVED)
		self.assertEqual(resolve_avs_status(AVS_STATUS_EXEMPTED, age=16), AVS_STATUS_EXEMPTED)

	def test_under_age_detected_when_nothing_declared(self):
		self.assertEqual(resolve_avs_status("", age=16, year=2026), AVS_STATUS_YOUTH)
		self.assertEqual(resolve_avs_status(None, age=17, year=2026), AVS_STATUS_YOUTH)

	def test_liable_from_the_start_age(self):
		self.assertEqual(resolve_avs_status("", age=18, year=2026), "")
		self.assertEqual(resolve_avs_status("", age=45, year=2026), "")

	def test_no_age_no_status(self):
		self.assertEqual(resolve_avs_status("", age=None), "")

	def test_past_the_reference_age_with_nothing_declared_is_a_pensioner(self):
		"""Guidelines 8.1.1: the birth date and the sex decide, a status is not required."""
		self.assertEqual(
			resolve_avs_status("", age=66, year=2026, past_reference_age=True), AVS_STATUS_RETIRED
		)

	def test_a_declared_waiver_still_wins_past_the_reference_age(self):
		self.assertEqual(
			resolve_avs_status(AVS_STATUS_RETIRED_WAIVED, age=66, year=2026, past_reference_age=True),
			AVS_STATUS_RETIRED_WAIVED,
		)


# //// Neoffice — the ages are read from the calendar year and the AVS 21 reference age (2026-09-23).
class TestAgeInYear(unittest.TestCase):
	def test_the_guidelines_example(self):
		"""8.1.1: born 7.8.2003, liable from 1.1.2021 — not from the birthday in August."""
		born = date(2003, 8, 7)
		self.assertEqual(resolve_avs_status("", age=age_in_year(born, 2020), year=2020), AVS_STATUS_YOUTH)
		self.assertEqual(resolve_avs_status("", age=age_in_year(born, 2021), year=2021), "")

	def test_an_apprentice_born_in_november_is_liable_from_january(self):
		"""Born 15.11.2008: 17 to the day in October 2026, yet liable since 1.1.2026."""
		self.assertEqual(age_in_year(date(2008, 11, 15), 2026), 18)

	def test_the_lpp_age_is_the_year_minus_the_year_of_birth(self):
		"""Born 20.11.1991: LPP age 35 for the whole of 2026 — the 10 % credit from January."""
		self.assertEqual(age_in_year(date(1991, 11, 20), 2026), 35)


class TestReferenceAge(unittest.TestCase):
	"""LAVS art. 21 and the AVS 21 transition as the guidelines tabulate it (8.1.1)."""

	def test_men(self):
		self.assertEqual(reference_age_months(date(1961, 8, 15), "male"), 65 * 12)

	def test_women_by_year_of_birth(self):
		cases = {1960: 64 * 12, 1961: 64 * 12 + 3, 1962: 64 * 12 + 6, 1963: 64 * 12 + 9, 1964: 65 * 12}
		for year, months in cases.items():
			self.assertEqual(reference_age_months(date(year, 5, 1), "female"), months, year)

	def test_unknown_sex_infers_nothing(self):
		self.assertIsNone(reference_age_months(date(1961, 8, 15), None))
		self.assertIsNone(retirement_start(date(1961, 8, 15), None))
		self.assertFalse(is_past_reference_age(date(1950, 1, 1), None, date(2026, 10, 1)))

	def test_pensioner_from_the_month_after(self):
		"""65 on 15.8.2026: still liable in August, a pensioner from 1 September."""
		born = date(1961, 8, 15)
		self.assertEqual(retirement_start(born, "male"), date(2026, 9, 1))
		self.assertFalse(is_past_reference_age(born, "male", date(2026, 8, 1)))
		self.assertTrue(is_past_reference_age(born, "male", date(2026, 9, 1)))

	def test_a_woman_born_in_1961(self):
		"""64 years and 3 months on 10.9.2025: a pensioner from 1 October 2025."""
		self.assertEqual(retirement_start(date(1961, 6, 10), "female"), date(2025, 10, 1))

	def test_a_woman_born_in_december_1962(self):
		"""64 years and 6 months on 10.6.2027: still liable throughout 2026."""
		born = date(1962, 12, 10)
		self.assertEqual(retirement_start(born, "female"), date(2027, 7, 1))
		self.assertFalse(is_past_reference_age(born, "female", date(2026, 12, 1)))

	def test_a_man_reaching_65_in_december(self):
		self.assertFalse(is_past_reference_age(date(1961, 12, 20), "male", date(2026, 10, 1)))
		self.assertEqual(retirement_start(date(1961, 12, 20), "male"), date(2027, 1, 1))


class TestOrdinaryEmployee(unittest.TestCase):
	def test_nothing_changes(self):
		out = apply_avs_status(6000, 6000, "", year=2026)
		self.assertEqual(out["avs_base"], 6000)
		self.assertEqual(out["ac_base"], 6000)
		self.assertEqual(out["exemption"], 0.0)


class TestNotLiable(unittest.TestCase):
	def test_youth_pays_neither_avs_nor_ac(self):
		"""An apprentice below the start age pays no AVS and no AC — only LAA applies."""
		out = apply_avs_status(2500, 2500, AVS_STATUS_YOUTH, year=2026)
		self.assertEqual(out["avs_base"], 0.0)
		self.assertEqual(out["ac_base"], 0.0)

	def test_exempted_pays_neither(self):
		out = apply_avs_status(6000, 6000, AVS_STATUS_EXEMPTED, year=2026)
		self.assertEqual(out["avs_base"], 0.0)
		self.assertEqual(out["ac_base"], 0.0)


class TestRetired(unittest.TestCase):
	def test_exemption_deducted_from_avs(self):
		out = apply_avs_status(6000, 6000, AVS_STATUS_RETIRED, year=2026)
		self.assertEqual(out["avs_base"], 6000 - AVS_RETIREMENT_EXEMPTION_MONTHLY)
		self.assertEqual(out["exemption"], AVS_RETIREMENT_EXEMPTION_MONTHLY)

	def test_no_ac_at_all_past_reference_age(self):
		"""No unemployment cover past the reference age (art. 2 al. 2 let. c LACI)."""
		self.assertEqual(apply_avs_status(6000, 6000, AVS_STATUS_RETIRED, year=2026)["ac_base"], 0.0)
		self.assertEqual(apply_avs_status(6000, 6000, AVS_STATUS_RETIRED_WAIVED, year=2026)["ac_base"], 0.0)

	def test_salary_below_the_exemption_never_goes_negative(self):
		out = apply_avs_status(1000, 1000, AVS_STATUS_RETIRED, year=2026)
		self.assertEqual(out["avs_base"], 0.0)
		self.assertEqual(out["exemption"], 1000)

	def test_exemption_is_monthly_and_scales_with_the_period(self):
		"""A quarterly run must deduct three months of exemption, not one."""
		out = apply_avs_status(18_000, 18_000, AVS_STATUS_RETIRED, months=3, year=2026)
		self.assertEqual(out["exemption"], 3 * AVS_RETIREMENT_EXEMPTION_MONTHLY)
		self.assertEqual(out["avs_base"], 18_000 - 3 * AVS_RETIREMENT_EXEMPTION_MONTHLY)

	def test_waived_exemption_leaves_the_full_avs_base(self):
		"""AVS 21 lets the employee waive the exemption to earn a higher pension."""
		out = apply_avs_status(6000, 6000, AVS_STATUS_RETIRED_WAIVED, year=2026)
		self.assertEqual(out["avs_base"], 6000)
		self.assertEqual(out["exemption"], 0.0)
