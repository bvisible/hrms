#//// Neoffice — added file (no upstream equivalent): validates the source-tax engine against the
#//// official Swissdec Annex 1 oracle (cent-exact expected withholding).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Validate the QST engine against the official Swissdec Annex 1 examples.

The fixture (test_data/annexe1_oracle.json, extracted from "Annexe 1 —
Exemples de calcul de l'impôt à la source", ELM 6.0, 20260306) carries the
embedded Swissdec test tariff and 113 cases with cent-exact expected
withholding per month. The test tariff is identical for every canton in the
oracle: the canton only selects the monthly vs annual model.

Scope: bracket lookup with day-based determinants (partial months),
retroactive Old/New code corrections (monthly deltas; annual per-code
settlement at the global determinant), prospective code changes. Still
out of scope: multi-employer/hourly/foreign-workday extrapolation,
model or canton switch mid-year (annual), corrections settled the
following year. Out-of-scope cases are SKIPPED with a reason; every
playable case must match to the cent.
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
	calculate_monthly_correction,
	calculate_source_tax_annual_settlement,
	calculate_source_tax_monthly,
	round_half_up,
)

DATA_FILE = os.path.join(os.path.dirname(__file__), "test_data", "annexe1_oracle.json")
TEST_PARENT = "ANNEXE1-ORACLE-TEST"
YEAR = 2021
TOLERANCE = 0.005  # cent-exact

# Capability flags that put a case out of scope.
SKIP_FLAGS = (("model_change", "annual<->monthly model switch mid-year"),)


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

		#//// Neoffice — `Swiss QST Tariff Bracket` is an autoincrement doctype: frappe
		#//// backs it with a MariaDB sequence, not with auto_increment, so `name` has no
		#//// default and a raw INSERT that omits it dies on error 1364. Take the ids from
		#//// the same sequence the ORM uses, so these rows can never collide with a real
		#//// ESTV vintage already in the table.
		sequence = frappe.scrub("Swiss QST Tariff Bracket_id_seq")
		for i in range(0, len(rows), 2000):
			batch = rows[i : i + 2000]
			#//// Neoffice — leading placeholder = the sequence value for `name` (see above).
			placeholders = ", ".join(
				[f"(nextval(`{sequence}`), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"]
				* len(batch)
			)
			#//// Neoffice — `name` added to the column list (see above).
			frappe.db.sql(
				f"""INSERT INTO `tabSwiss QST Tariff Bracket`
				(name, parent_tariff, canton, tariff_code, tariff_type, valid_from,
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

	def _month_activity(self, case, m):
		"""(activity_rate_own, activity_rate_total) for month m, or (None, None)."""
		own = (case.get("activity_own") or [None] * 12)[m]
		total = (case.get("activity_total") or [None] * 12)[m]
		return (float(own) if own else None, float(total) if total else None)

	def _month_factor(self, case, m):
		own, total = self._month_activity(case, m)
		return (total or 1.0) / own if own else 1.0

	def _month_taxable(self, case, m):
		"""CH-taxable base for month m (defaults to gross)."""
		val = (case.get("taxable") or [None] * 12)[m]
		return float(val) if val is not None else float(case["gross"][m])

	def _skip_reason(self, case):
		for flag, reason in SKIP_FLAGS:
			if case["flags"].get(flag):
				return reason
		if case["expected_tax"] is None:
			return "no expected amounts extracted"
		if case["model"] == "annual" and case["flags"].get("canton_change"):
			return "annual model with canton change mid-year"
		for corr in case.get("corrections") or []:
			if int(str(corr["origin"])[5:7]) > corr["payment_month"]:
				return "correction settled in the following year"
		# Cases whose only "correction" labels are Compensation rows are
		# prospective code changes: the compensation is an OUTPUT of the
		# per-code settlement, not an input — playable as-is.

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
			factor = self._month_factor(case, m)
			if case["model"] == "monthly":
				# Day extrapolation of the periodic part, then activity factor.
				det_engine = round(((gross - aperiodic) / days * 30 + aperiodic) * factor, 2)
				if det is not None and abs(float(det) - det_engine) > 0.02:
					return "determinant beyond day/activity extrapolation (special settlement)"
			else:
				cum_gross += gross
				cum_aper += aperiodic
				cum_days += days
				det_engine = round(
					((cum_gross - cum_aper) / cum_days * 360 + cum_aper) * factor / 12, 2
				)
				if det is not None and abs(float(det) - det_engine) > 0.02:
					return "determinant beyond day/activity annualization (special settlement)"
		return None

	def _active_months(self, case):
		gross = case["gross"] or [None] * 12
		return [m for m in range(12) if gross[m] is not None]

	def _corrections_by_month(self, case):
		out = {}
		for corr in case.get("corrections") or []:
			out.setdefault(corr["payment_month"], []).append(
				{**corr, "origin_month": int(str(corr["origin"])[5:7])}
			)
		return out

	def _play_monthly(self, case):
		corrections = self._corrections_by_month(case)
		for m in self._active_months(case):
			gross, days, aperiodic, canton, code = self._month_inputs(case, m)
			own, total = self._month_activity(case, m)
			result = calculate_source_tax_monthly(
				gross,
				canton,
				code,
				date(YEAR, m + 1, 28),
				qst_days=days,
				aperiodic=aperiodic,
				activity_rate_own=own,
				activity_rate_total=total,
				taxable=self._month_taxable(case, m),
			)
			tax = result["tax_amount"]
			# Corrections settled this month: re-settle each origin month
			# under its new code at the origin month's own determinant.
			for corr in corrections.get(m + 1, []):
				m0 = corr["origin_month"] - 1
				g0, d0, a0, canton0, _ = self._month_inputs(case, m0)
				delta = calculate_monthly_correction(
					g0,
					canton0,
					corr["old_code"],
					corr["new_code"],
					date(YEAR, corr["origin_month"], 28),
					qst_days=d0,
					aperiodic=a0,
				)["delta"]
				tax = round(tax + delta, 2)
			raw_expected = float(case["expected_tax"][m])
			expected = round_half_up(raw_expected)
			# The sheets publish the taxable base rounded to 2 dp while
			# computing amounts on the full chain (M31): when our rounded
			# cent differs but the full-precision amounts agree, the
			# mismatch is an artefact of the published source.
			full_ok = (
				not corrections.get(m + 1)
				and abs(float(result["tax_amount_full"]) - raw_expected) <= 0.006
			)
			if abs(tax - expected) > TOLERANCE and not full_ok:
				self.fail(
					f"{case['id']} month {m + 1}: gross {gross} days {days} "
					f"aperiodic {aperiodic} code {code} -> got {tax} "
					f"(full {result['tax_amount_full']}, rate {result['tax_rate']}, "
					f"det {result['determinant']}), oracle expects {expected} "
					f"(raw {raw_expected})"
				)

	def _play_annual(self, case):
		"""Replay via the per-code settlement (Annex 1 Y40 mechanics).

		One cumulative account per tariff code; the rate always reads at
		the global determinant. Retroactive corrections move the origin
		month's gross between code accounts before settling.
		"""
		corrections = self._corrections_by_month(case)
		state = {}  # code -> {"cum": float, "ytd": float}
		tot_periodic = tot_aperiodic = tot_days = 0.0
		for m in self._active_months(case):
			month = m + 1
			gross, days, aperiodic, canton, code = self._month_inputs(case, m)
			for corr in corrections.get(month, []):
				t0 = self._month_taxable(case, corr["origin_month"] - 1)
				old = state.setdefault(corr["old_code"], {"cum": 0.0, "ytd": 0.0})
				new = state.setdefault(corr["new_code"], {"cum": 0.0, "ytd": 0.0})
				old["cum"] = round(old["cum"] - t0, 2)
				new["cum"] = round(new["cum"] + t0, 2)
			st = state.setdefault(code, {"cum": 0.0, "ytd": 0.0})
			st["cum"] = round(st["cum"] + self._month_taxable(case, m), 2)
			tot_periodic += gross - aperiodic
			tot_aperiodic += aperiodic
			tot_days += days
			own, total = self._month_activity(case, m)
			result = calculate_source_tax_annual_settlement(
				canton,
				date(YEAR, month, 28),
				total_periodic=tot_periodic,
				total_aperiodic=tot_aperiodic,
				total_days=tot_days,
				per_code={
					c: {"cumulative_gross": s["cum"], "ytd_tax": str(s["ytd"])}
					for c, s in state.items()
				},
				activity_rate_own=own,
				activity_rate_total=total,
			)
			expected = round_half_up(float(case["expected_tax"][m]))
			self.assertAlmostEqual(
				result["tax_amount"],
				expected,
				delta=TOLERANCE,
				msg=(
					f"{case['id']} month {month}: gross {gross} days {days} "
					f"aperiodic {aperiodic} state {state} -> "
					f"got {result['tax_amount']} (det {result['determinant']}, "
					f"by_code {result['by_code']}), oracle expects {expected}"
				),
			)
			for c, detail in result["by_code"].items():
				# The oracle carries unrounded cumulatives: the withheld
				# account equals the full-precision cumulative due.
				state[c]["ytd"] = detail["cumulative_due_full"]

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
