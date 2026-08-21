# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Validate the QST engine against the official Swissdec Annex 1 examples.

The fixture (test_data/annexe1_oracle.json, extracted from "Annexe 1 —
Exemples de calcul de l'impôt à la source", ELM 6.0, 20260306) carries the
embedded Swissdec test tariff and 113 cases with cent-exact expected
withholding per month. The test tariff is identical for every canton in the
oracle: the canton only selects the monthly vs annual model.

Level-1 scope: plain bracket lookup on full months — no determinant
extrapolation (partial months, multi-employer, hourly, foreign workdays),
no retroactive corrections, no model/canton switch mid-year on the annual
model. Out-of-scope cases are SKIPPED with a reason and reported in the
summary; every playable case must match to the cent.
"""

import json
import os
import unittest
from collections import Counter
from datetime import date

import frappe
from frappe.utils import now_datetime

from hrms.regional.switzerland.constants import ANNUAL_MODEL_CANTONS
from hrms.regional.switzerland.source_tax import (
	calculate_source_tax_annual,
	calculate_source_tax_monthly,
)

DATA_FILE = os.path.join(os.path.dirname(__file__), "test_data", "annexe1_oracle.json")
TEST_PARENT = "ANNEXE1-ORACLE-TEST"
YEAR = 2021
TOLERANCE = 0.005  # cent-exact

# Capability flags that put a case out of scope.
SKIP_FLAGS = (
	("corrections", "retroactive corrections (Old/New)"),
	("multi_employer", "multi-employer determinant extrapolation"),
	("hourly", "hourly-wage determinant extrapolation"),
	("foreign_days", "foreign workdays split"),
	("model_change", "annual<->monthly model switch mid-year"),
)


def _natural_model(canton):
	return "annual" if canton in ANNUAL_MODEL_CANTONS else "monthly"


class TestAnnexe1Oracle(unittest.TestCase):
	oracle = None
	results = None  # {case_id: ("PASS"|"SKIP"|"FAIL", detail)}

	@classmethod
	def setUpClass(cls):
		with open(DATA_FILE) as f:
			cls.oracle = json.load(f)
		cls.results = {}
		cls._install_test_tariffs()

	@classmethod
	def tearDownClass(cls):
		frappe.db.sql(
			"DELETE FROM `tabSwiss QST Tariff Bracket` WHERE parent_tariff = %s", TEST_PARENT
		)
		frappe.db.commit()

	@classmethod
	def _install_test_tariffs(cls):
		"""Insert the oracle tariff for every canton seen in the cases.

		Each canton gets the tariff table of its natural model (BE/AG the
		monthly workbook's, TI/VD the annual workbook's), valid from
		YEAR-01-01 — coexists with any real ESTV vintage in the table.
		"""
		frappe.db.sql(
			"DELETE FROM `tabSwiss QST Tariff Bracket` WHERE parent_tariff = %s", TEST_PARENT
		)
		cantons = set()
		for case in cls.oracle["cases"]:
			cantons.update(c for c in (case["cantons"] or []) if c)

		now = now_datetime()
		rows = []
		for canton in sorted(cantons):
			tariffs = cls.oracle["tariffs"][_natural_model(canton)]
			for code, brackets in tariffs.items():
				for i, (threshold, rate) in enumerate(brackets):
					step = (
						brackets[i + 1][0] - threshold if i + 1 < len(brackets) else 50
					)
					rows.append(
						(
							TEST_PARENT, canton, code, "SAL", f"{YEAR}-01-01",
							threshold, step, 0, 0, rate,
							now, now, "Administrator", "Administrator",
						)
					)

		for i in range(0, len(rows), 2000):
			batch = rows[i : i + 2000]
			placeholders = ", ".join(
				["(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(batch)
			)
			frappe.db.sql(
				f"""INSERT INTO `tabSwiss QST Tariff Bracket`
				(parent_tariff, canton, tariff_code, tariff_type, valid_from,
				 income_from, income_step, num_children, tax_amount, tax_rate,
				 creation, modified, owner, modified_by)
				VALUES {placeholders}""",
				[v for row in batch for v in row],
			)
		frappe.db.commit()

	# ------------------------------------------------------------------ #

	def _month_inputs(self, case, m):
		"""Engine inputs for month m: (gross, days, aperiodic, canton, code)."""
		gross = float(case["gross"][m])
		days = (case["days_as"] or [None] * 12)[m] or 30
		periodic = (case["determinant_periodic"] or [None] * 12)[m]
		periodic = float(periodic) if periodic is not None else gross
		aperiodic = round(max(gross - periodic, 0.0), 2)
		return gross, float(days), aperiodic, case["cantons"][m], case["codes"][m]

	def _skip_reason(self, case):
		for flag, reason in SKIP_FLAGS:
			if case["flags"].get(flag):
				return reason
		if case["expected_tax"] is None:
			return "no expected amounts extracted"
		if case["model"] == "annual" and case["flags"].get("code_change"):
			return "annual model with tariff-code change (per-code settlement)"
		if case["model"] == "annual" and case["flags"].get("canton_change"):
			return "annual model with canton change mid-year"

		active = self._active_months(case)
		if not active:
			return "no active months"
		cum_gross = cum_aper = cum_days = 0.0
		for m in active:
			canton = (case["cantons"] or [None] * 12)[m]
			if not canton:
				return "missing canton on an active month"
			if _natural_model(canton) != case["model"]:
				return f"canton {canton} not a {case['model']}-model canton"
			if case["expected_tax"][m] is None:
				return "missing expected amount on an active month"
			gross, days, aperiodic, _, _ = self._month_inputs(case, m)
			det = (case["determinant"] or [None] * 12)[m]
			if case["model"] == "monthly":
				# The engine extrapolates the periodic part to 30 days.
				det_engine = round((gross - aperiodic) / days * 30 + aperiodic, 2)
				if det is not None and abs(float(det) - det_engine) > 0.01:
					return "determinant beyond day-extrapolation (special settlement)"
			else:
				cum_gross += gross
				cum_aper += aperiodic
				cum_days += days
				det_engine = round(
					((cum_gross - cum_aper) / cum_days * 360 + cum_aper) / 12, 2
				)
				if det is not None and abs(float(det) - det_engine) > 0.01:
					return "determinant beyond day-annualization (special settlement)"
		return None

	def _active_months(self, case):
		gross = case["gross"] or [None] * 12
		return [m for m in range(12) if gross[m] is not None]

	def _play_monthly(self, case):
		for m in self._active_months(case):
			gross, days, aperiodic, canton, code = self._month_inputs(case, m)
			result = calculate_source_tax_monthly(
				gross, canton, code, date(YEAR, m + 1, 28), qst_days=days, aperiodic=aperiodic
			)
			expected = round(float(case["expected_tax"][m]), 2)
			self.assertAlmostEqual(
				result["tax_amount"],
				expected,
				delta=TOLERANCE,
				msg=(
					f"{case['id']} month {m + 1}: gross {gross} days {days} "
					f"aperiodic {aperiodic} code {code} -> got {result['tax_amount']} "
					f"(rate {result['tax_rate']}, det {result['determinant']}), "
					f"oracle expects {expected}"
				),
			)

	def _play_annual(self, case):
		ytd_gross = 0.0
		ytd_tax = 0.0
		ytd_days = 0.0
		ytd_aperiodic = 0.0
		month_num = 0
		for m in self._active_months(case):
			month_num += 1
			gross, days, aperiodic, canton, code = self._month_inputs(case, m)
			result = calculate_source_tax_annual(
				gross,
				canton,
				code,
				ytd_gross,
				ytd_tax,
				month_num,
				date(YEAR, m + 1, 28),
				qst_days=days,
				ytd_days=ytd_days,
				aperiodic=aperiodic,
				ytd_aperiodic=ytd_aperiodic,
			)
			expected = round(float(case["expected_tax"][m]), 2)
			self.assertAlmostEqual(
				result["tax_amount"],
				expected,
				delta=TOLERANCE,
				msg=(
					f"{case['id']} month {m + 1}: gross {gross} days {days} "
					f"aperiodic {aperiodic} ytd {ytd_gross}/{ytd_days}d -> "
					f"got {result['tax_amount']} (rate {result['tax_rate']}, "
					f"det {result['determinant']}), oracle expects {expected}"
				),
			)
			ytd_gross += gross
			ytd_tax += result["tax_amount"]
			ytd_days += days
			ytd_aperiodic += aperiodic

	def _run_cases(self, model):
		for case in self.oracle["cases"]:
			if case["model"] != model:
				continue
			reason = self._skip_reason(case)
			if reason:
				self.results[case["id"]] = ("SKIP", reason)
				continue
			with self.subTest(case=case["id"], title=case["title"][:70]):
				try:
					if model == "monthly":
						self._play_monthly(case)
					else:
						self._play_annual(case)
				except AssertionError as exc:
					self.results[case["id"]] = ("FAIL", str(exc)[:200])
					raise
				else:
					self.results[case["id"]] = ("PASS", "")

	def test_monthly_cases(self):
		"""Every in-scope monthly-model case matches the oracle to the cent."""
		self._run_cases("monthly")

	def test_annual_cases(self):
		"""Every in-scope annual-model case matches the oracle to the cent."""
		self._run_cases("annual")

	def test_zz_coverage_report(self):
		"""Print the PASS/SKIP/FAIL map and enforce minimum coverage."""
		passed = sorted(k for k, v in self.results.items() if v[0] == "PASS")
		failed = sorted(k for k, v in self.results.items() if v[0] == "FAIL")
		skipped = [(k, v[1]) for k, v in sorted(self.results.items()) if v[0] == "SKIP"]

		print("\n===== Annex 1 oracle coverage =====")
		print(f"PASS ({len(passed)}): {', '.join(passed)}")
		reasons = Counter(reason for _, reason in skipped)
		print(f"SKIP ({len(skipped)}):")
		for reason, n in reasons.most_common():
			print(f"  {n:3d}  {reason}")
		if failed:
			print(f"FAIL ({len(failed)}): {', '.join(failed)}")

		self.assertFalse(failed, f"oracle cases failed: {failed}")
		# Guard against an extraction bug silently skipping everything.
		self.assertGreaterEqual(
			len(passed), 12, "fewer playable oracle cases than expected — check the fixture"
		)
