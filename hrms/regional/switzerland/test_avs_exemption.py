# //// Neoffice — added file (no upstream equivalent): unit tests of the AVS liability rules.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest

from hrms.regional.switzerland.avs_exemption import apply_avs_status, resolve_avs_status
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
		self.assertEqual(
			apply_avs_status(6000, 6000, AVS_STATUS_RETIRED_WAIVED, year=2026)["ac_base"], 0.0
		)

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
