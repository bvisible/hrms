# //// Neoffice — added file (no upstream equivalent): unit tests of the wage type catalog integrity
# //// and of the per-component insurance bases.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Tests for Swiss Wage Type catalog and per-component insurance base logic."""

import unittest
from unittest.mock import MagicMock, patch

from hrms.regional.switzerland.wage_type_data import get_swiss_wage_types


class TestWageTypeData(unittest.TestCase):
	"""Tests for the wage type catalog data integrity."""

	@classmethod
	def setUpClass(cls):
		cls.wage_types = get_swiss_wage_types()

	def test_catalog_has_entries(self):
		"""Catalog should contain 150+ standard wage types."""
		self.assertGreaterEqual(len(self.wage_types), 150)

	def test_codes_are_numeric(self):
		"""All wage type codes must be numeric strings."""
		for wt in self.wage_types:
			self.assertTrue(
				wt["code"].isdigit(),
				f"Code '{wt['code']}' for '{wt['wage_type_name']}' is not numeric",
			)

	def test_codes_are_unique(self):
		"""All codes must be unique."""
		codes = [wt["code"] for wt in self.wage_types]
		self.assertEqual(len(codes), len(set(codes)), "Duplicate codes found")

	def test_names_are_non_empty(self):
		"""All wage types must have a name."""
		for wt in self.wage_types:
			self.assertTrue(wt["wage_type_name"].strip(), f"Empty name for code {wt['code']}")

	def test_valid_types(self):
		"""Type must be Earning, Deduction, or Informational."""
		valid_types = {"Earning", "Deduction", "Informational"}
		for wt in self.wage_types:
			self.assertIn(
				wt["type"],
				valid_types,
				f"Invalid type '{wt['type']}' for code {wt['code']}",
			)

	def test_flags_are_binary(self):
		"""All social insurance flags must be 0 or 1."""
		flag_fields = [
			"subject_to_avs",
			"subject_to_ac",
			"subject_to_laa",
			"subject_to_ijm",
			"subject_to_lpp",
			"subject_to_imp",
		]
		for wt in self.wage_types:
			for field in flag_fields:
				self.assertIn(
					wt[field],
					(0, 1),
					f"Flag {field}={wt[field]} for code {wt['code']} is not 0 or 1",
				)

	def test_common_codes_present(self):
		"""Key wage type codes used in Swiss payroll must exist."""
		required_codes = {
			"1000",  # Monthly salary
			"1005",  # Hourly salary
			"1060",  # Overtime
			"1160",  # Vacation allowance
			"1181",  # 13th month
			"1210",  # Bonus
			"2000",  # APG
			"2035",  # IJM sickness
			"2040",  # Maternity
			"3000",  # Child allowance
			"5010",  # AVS contribution
			"5020",  # AC contribution
			"5054",  # LPP contribution
			"5060",  # Source tax
			"6000",  # Travel expenses
		}
		catalog_codes = {wt["code"] for wt in self.wage_types}
		missing = required_codes - catalog_codes
		self.assertEqual(missing, set(), f"Missing required codes: {missing}")

	def test_common_flag_set(self):
		"""At least 20 entries should be marked as common."""
		common_count = sum(1 for wt in self.wage_types if wt.get("is_common"))
		self.assertGreaterEqual(common_count, 20)

	def test_base_salary_flags(self):
		"""Monthly salary (1000) should be subject to all social charges."""
		wt = self._get_by_code("1000")
		self.assertEqual(wt["subject_to_avs"], 1)
		self.assertEqual(wt["subject_to_ac"], 1)
		self.assertEqual(wt["subject_to_laa"], 1)
		self.assertEqual(wt["subject_to_ijm"], 1)
		self.assertEqual(wt["subject_to_lpp"], 1)
		self.assertEqual(wt["subject_to_imp"], 1)

	def test_child_allowance_flags(self):
		"""Child allowance (3000) exempt from social charges but subject to source tax."""
		wt = self._get_by_code("3000")
		self.assertEqual(wt["subject_to_avs"], 0)
		self.assertEqual(wt["subject_to_ac"], 0)
		self.assertEqual(wt["subject_to_laa"], 0)
		self.assertEqual(wt["subject_to_ijm"], 0)
		self.assertEqual(wt["subject_to_lpp"], 0)
		self.assertEqual(wt["subject_to_imp"], 1)  # taxable income

	def test_apg_partial_flags(self):
		"""APG (2000): AVS/AC, IJM and source tax — never LAA (Swissdec guidelines 6.0, 5.2.1).

		//// Neoffice — IJM was 0 here, pinning the catalogue error the guidelines contradict.
		"""
		wt = self._get_by_code("2000")
		self.assertEqual(wt["subject_to_avs"], 1)
		self.assertEqual(wt["subject_to_ac"], 1)
		self.assertEqual(wt["subject_to_laa"], 0)
		self.assertEqual(wt["subject_to_ijm"], 1)
		self.assertEqual(wt["subject_to_lpp"], 0)
		self.assertEqual(wt["subject_to_imp"], 1)

	def test_ijm_sickness_imp_only(self):
		"""IJM sickness allowance (2035) should only be subject to source tax."""
		wt = self._get_by_code("2035")
		self.assertEqual(wt["subject_to_avs"], 0)
		self.assertEqual(wt["subject_to_ac"], 0)
		self.assertEqual(wt["subject_to_laa"], 0)
		self.assertEqual(wt["subject_to_ijm"], 0)
		self.assertEqual(wt["subject_to_lpp"], 0)
		self.assertEqual(wt["subject_to_imp"], 1)

	def test_expense_reimbursements_exempt(self):
		"""Expense codes (6000-6070) should be exempt from all charges."""
		expense_codes = ["6000", "6001", "6002", "6010", "6040", "6050"]
		for code in expense_codes:
			wt = self._get_by_code(code)
			if wt is None:
				continue
			total_flags = sum(
				wt[f]
				for f in [
					"subject_to_avs",
					"subject_to_ac",
					"subject_to_laa",
					"subject_to_ijm",
					"subject_to_lpp",
					"subject_to_imp",
				]
			)
			# Exception: 6060 (expat flat-rate) is subject to ALL
			if code != "6060":
				self.assertEqual(
					total_flags,
					0,
					f"Expense code {code} should be exempt but has {total_flags} flags set",
				)

	def test_deductions_have_no_insurance_flags(self):
		"""Deduction wage types should have all insurance flags = 0.

		Exception: the 2000-2099 correction/absence range (e.g. 2050 third-party
		indemnity correction, 2051 net salary correction, 2060 RHT/ITP deduction)
		legitimately carries insurance-base flags because these lines correct the
		insured bases themselves (per the Swissdec wage type reference).
		"""
		for wt in self.wage_types:
			if wt["type"] == "Deduction":
				if 2000 <= int(wt["code"]) < 2100:
					continue
				total_flags = sum(
					wt[f]
					for f in [
						"subject_to_avs",
						"subject_to_ac",
						"subject_to_laa",
						"subject_to_ijm",
						"subject_to_lpp",
						"subject_to_imp",
					]
				)
				self.assertEqual(
					total_flags,
					0,
					f"Deduction {wt['code']} ({wt['wage_type_name']}) should have 0 flags, got {total_flags}",
				)

	def test_lohnausweis_positions_valid(self):
		"""All lohnausweis_position values should be from the valid set."""
		valid_positions = {
			"",
			"1",
			"2.1",
			"2.2",
			"2.3",
			"3",
			"4",
			"5",
			"6",
			"7",
			"9",
			"10.1",
			"10.2",
			"12",
			"13.1.1",
			"13.1.2",
			"13.2.1",
			"13.2.2",
			"13.2.3",
			"13.3",
			"14",
		}
		for wt in self.wage_types:
			self.assertIn(
				wt["lohnausweis_position"],
				valid_positions,
				f"Invalid position '{wt['lohnausweis_position']}' for code {wt['code']}",
			)

	def _get_by_code(self, code):
		"""Find a wage type by code."""
		for wt in self.wage_types:
			if wt["code"] == code:
				return wt
		return None


# code -> (type, AVS/AC, LAA, IJM, LPP, source tax, negative, bases only) as the sample wage type
# table of the Swissdec guidelines 6.0 (edition 06.03.2026, 5.2.1) gives them, for every code our
# catalogue shares with it under the same meaning. The LPP column is our own flag, not theirs: it
# only feeds the salary annualised for an employee paid by the hour.
SWISSDEC_60 = {
	"1000": ("Earning", 1, 1, 1, 1, 1, 0, 0),
	"1165": ("Earning", 1, 1, 1, 1, 1, 0, 0),  # 1166 "Paiement des vacances" there
	"1210": ("Earning", 1, 1, 1, 1, 1, 0, 0),
	"1400": ("Earning", 0, 0, 0, 0, 1, 0, 0),
	"1401": ("Earning", 1, 0, 1, 0, 1, 0, 0),
	"1920": ("Earning", 1, 1, 1, 0, 1, 0, 1),
	"1971": ("Earning", 0, 0, 0, 0, 1, 0, 0),
	"1976": ("Earning", 0, 0, 0, 0, 1, 0, 0),
	"1977": ("Earning", 1, 1, 1, 1, 1, 0, 0),
	"1978": ("Earning", 1, 1, 1, 1, 1, 0, 0),
	"1979": ("Earning", 1, 1, 1, 1, 1, 0, 0),
	"1980": ("Earning", 0, 0, 0, 0, 0, 0, 0),
	"2000": ("Earning", 1, 0, 1, 0, 1, 0, 0),
	"2005": ("Earning", 1, 1, 1, 0, 1, 0, 0),
	"2020": ("Earning", 1, 0, 1, 0, 1, 0, 0),
	"2021": ("Earning", 0, 0, 0, 0, 0, 0, 0),
	"2025": ("Earning", 1, 0, 1, 0, 1, 0, 0),
	"2026": ("Earning", 0, 0, 0, 0, 0, 0, 0),
	"2030": ("Earning", 0, 0, 0, 0, 1, 0, 0),
	"2031": ("Earning", 0, 0, 0, 0, 0, 0, 0),
	"2035": ("Earning", 0, 0, 0, 0, 1, 0, 0),
	"2040": ("Earning", 1, 0, 1, 0, 1, 0, 0),  # 2001 "Indemnité maternité" there
	"2050": ("Earning", 1, 1, 1, 0, 1, 1, 0),
	"2060": ("Earning", 0, 0, 0, 0, 1, 1, 0),
	"2065": ("Earning", 1, 1, 1, 1, 0, 0, 1),  # LPP: "LPP rétroactive" 1 there
	"2070": ("Earning", 0, 0, 0, 0, 1, 0, 0),
	"2075": ("Earning", 0, 0, 0, 0, 1, 0, 0),
	"3000": ("Earning", 0, 0, 0, 0, 1, 0, 0),
}


class TestCatalogueMatchesSwissdec60(unittest.TestCase):
	"""//// Neoffice — the catalogue against the official sample table, code by code (2026-09-23)."""

	def test_every_shared_code_is_subject_as_swissdec_says(self):
		catalogue = {wt["code"]: wt for wt in get_swiss_wage_types()}
		for code, expected in SWISSDEC_60.items():
			wt = catalogue[code]
			actual = (
				wt["type"],
				wt["subject_to_avs"],
				wt["subject_to_laa"],
				wt["subject_to_ijm"],
				wt["subject_to_lpp"],
				wt["subject_to_imp"],
				wt["is_negative"],
				wt["bases_only"],
			)
			self.assertEqual(actual, expected, f"wage type {code} ({wt['wage_type_name']})")
			self.assertEqual(wt["subject_to_ac"], wt["subject_to_avs"], f"AVS and AC go together ({code})")

	def test_a_bases_only_wage_type_is_never_paid(self):
		for wt in get_swiss_wage_types():
			if wt["bases_only"]:
				self.assertEqual(wt.get("do_not_include_in_total"), 1, wt["code"])

	def test_certificate_boxes_the_guidelines_fix(self):
		"""FAQ 2026 on the salary certificate, 1.6: income replacement benefits in box 7."""
		catalogue = {wt["code"]: wt for wt in get_swiss_wage_types()}
		self.assertEqual(catalogue["1980"]["lohnausweis_position"], "13.3")  # training (Rz 61)
		for code in ("2000", "2005", "2020", "2025", "2030", "2035", "2040", "2070"):
			self.assertEqual(catalogue[code]["lohnausweis_position"], "7", code)
		# What the employer bears stays with the salary: the correction, the short-time work
		# deduction and the waiting day. Family allowances too (Wegleitung Rz 15).
		for code in ("2050", "2060", "2075", "3000", "3010"):
			self.assertEqual(catalogue[code]["lohnausweis_position"], "1", code)


class TestSwissdecBaseExamples(unittest.TestCase):
	"""The worked examples of the Swissdec guidelines 6.0 (8.7.2), through utils.sum_insurance_bases."""

	@staticmethod
	def _row(code, amount, no_total=0):
		wt = {w["code"]: w for w in get_swiss_wage_types()}[code]
		row = {f"ch_subject_to_{k}": wt[f"subject_to_{k}"] for k in ("avs", "ac", "laa", "ijm", "lpp", "imp")}
		row.update(
			ch_wage_type_code=code,
			ch_bases_only=wt["bases_only"],
			do_not_include_in_total=no_total or wt.get("do_not_include_in_total", 0),
			# A "-" wage type reaches the bases negative (payroll_hooks._apply_negative_wage_types).
			amount=-amount if wt["is_negative"] else amount,
		)
		return row

	def _bases(self, *lines):
		from hrms.regional.switzerland.utils import sum_insurance_bases

		return sum_insurance_bases([self._row(code, amount) for code, amount in lines])

	def test_apg_with_the_salary_continued(self):
		"""8.7.2.1: 7'000 + APG 550 - correction 550 -> gross 7'000, LAA 6'450, AVS 7'000."""
		bases = self._bases(("1000", 7000), ("2000", 550), ("2050", 550))
		self.assertEqual((bases["gross"], bases["laa"], bases["avs"]), (7000, 6450, 7000))

	def test_apg_without_the_salary_continued(self):
		"""8.7.2.1: hourly 2'250.50 + APG 550 -> gross 2'800.50, LAA 2'250.50, AVS 2'800.50."""
		bases = self._bases(("1005", 2250.50), ("2000", 550))
		self.assertEqual((bases["gross"], bases["laa"], bases["avs"]), (2800.50, 2250.50, 2800.50))

	def test_military_compensation_with_the_salary_continued(self):
		"""8.7.2.2: the CCM is subject to LAA too -> gross, LAA and AVS all 7'000."""
		bases = self._bases(("1000", 7000), ("2005", 550), ("2050", 550))
		self.assertEqual((bases["gross"], bases["laa"], bases["avs"]), (7000, 7000, 7000))

	def test_accident_daily_allowance_with_the_salary_continued(self):
		"""8.7.2.4: exempt from AVS and LAA -> gross 7'000, LAA 6'450, AVS 6'450."""
		bases = self._bases(("1000", 7000), ("2030", 550), ("2050", 550))
		self.assertEqual((bases["gross"], bases["laa"], bases["avs"]), (7000, 6450, 6450))

	def test_short_time_work_with_the_salary_continued(self):
		"""8.7.2.5: 7'000 - 1'500 + 1'050 + 150 -> gross 6'700, LAA and AVS 7'000."""
		bases = self._bases(("1000", 7000), ("2060", 1500), ("2070", 1050), ("2075", 150))
		self.assertEqual((bases["gross"], bases["laa"], bases["avs"]), (6700, 7000, 7000))
		self.assertEqual(bases["imp"], 6700)  # source tax on what is actually earned

	def test_short_time_work_without_the_salary_continued(self):
		"""8.7.2.5: hourly 4'600 + loss 900 (bases only) + 600 + 120 -> gross 5'320, bases 5'500."""
		bases = self._bases(("1005", 4600), ("2065", 900), ("2070", 600), ("2075", 120))
		self.assertEqual((bases["gross"], bases["laa"], bases["avs"]), (5320, 5500, 5500))
		self.assertEqual(bases["imp"], 5320)

	def test_tips_raise_the_bases_without_being_paid(self):
		"""1920: 800 of tips on 6'000 -> gross 6'000, AVS and LAA 6'800."""
		bases = self._bases(("1000", 6000), ("1920", 800))
		self.assertEqual((bases["gross"], bases["avs"], bases["laa"], bases["lpp"]), (6000, 6800, 6800, 6000))


def _component_fields(avs, ac, laa, ijm, lpp, imp, wage_type="X"):
	"""The Salary Component fields sum_insurance_bases reads; wage_type=None for a legacy one."""
	return {
		"ch_subject_to_avs": avs,
		"ch_subject_to_ac": ac,
		"ch_subject_to_laa": laa,
		"ch_subject_to_ijm": ijm,
		"ch_subject_to_lpp": lpp,
		"ch_subject_to_imp": imp,
		"ch_wage_type_code": wage_type,
	}


class TestInsuranceBaseTotals(unittest.TestCase):
	"""Tests for per-component insurance base calculation in payroll_hooks.

	Uses mock objects to simulate Salary Slip earnings and Salary Component flags
	without requiring a Frappe database connection.
	"""

	def _make_earning_row(self, component, amount):
		"""Create a mock earning row shaped like a real Salary Detail."""
		import frappe

		return frappe._dict(
			salary_component=component,
			default_amount=amount,
			amount=amount,
			do_not_include_in_total=0,
		)

	def _make_mock_doc(self, earnings):
		"""Create a mock Salary Slip doc with earnings."""
		doc = MagicMock()
		doc.get.return_value = earnings
		return doc

	@patch("hrms.regional.switzerland.payroll_hooks._get_component_insurance_flags")
	def test_all_flags_set(self, mock_flags):
		"""When all earnings are subject to all insurances, all bases equal gross."""
		from hrms.regional.switzerland.payroll_hooks import _get_insurance_base_totals

		mock_flags.return_value = _component_fields(1, 1, 1, 1, 1, 1)

		earnings = [
			self._make_earning_row("Basic", 8000),
			self._make_earning_row("Overtime Pay", 500),
		]
		doc = self._make_mock_doc(earnings)

		result = _get_insurance_base_totals(doc)

		self.assertEqual(result["avs_base"], 8500)
		self.assertEqual(result["ac_base"], 8500)
		self.assertEqual(result["laa_base"], 8500)
		self.assertEqual(result["ijm_base"], 8500)
		self.assertEqual(result["lpp_base"], 8500)
		self.assertEqual(result["imp_base"], 8500)
		self.assertEqual(result["gross_total"], 8500)

	@patch("hrms.regional.switzerland.payroll_hooks._get_component_insurance_flags")
	def test_mixed_flags(self, mock_flags):
		"""Earnings with different flags produce different base totals."""
		from hrms.regional.switzerland.payroll_hooks import _get_insurance_base_totals

		def side_effect(comp):
			if comp == "Basic":
				return _component_fields(1, 1, 1, 1, 1, 1)
			elif comp == "Child Allowance":
				# Exempt from social charges but subject to source tax
				return _component_fields(0, 0, 0, 0, 0, 1)
			elif comp == "APG Allowance":
				return _component_fields(1, 1, 0, 0, 0, 1)
			return _component_fields(0, 0, 0, 0, 0, 0, wage_type=None)

		mock_flags.side_effect = side_effect

		earnings = [
			self._make_earning_row("Basic", 8000),
			self._make_earning_row("Child Allowance", 300),
			self._make_earning_row("APG Allowance", 1000),
		]
		doc = self._make_mock_doc(earnings)

		result = _get_insurance_base_totals(doc)

		# gross_total includes all earnings
		self.assertEqual(result["gross_total"], 9300)

		# AVS: Basic (8000) + APG (1000) = 9000 (not Child Allowance)
		self.assertEqual(result["avs_base"], 9000)

		# AC: Basic (8000) + APG (1000) = 9000
		self.assertEqual(result["ac_base"], 9000)

		# LAA: Basic (8000) only
		self.assertEqual(result["laa_base"], 8000)

		# IJM: Basic (8000) only
		self.assertEqual(result["ijm_base"], 8000)

		# LPP: Basic (8000) only
		self.assertEqual(result["lpp_base"], 8000)

		# IMP: Basic (8000) + Child Allowance (300) + APG (1000) = 9300
		self.assertEqual(result["imp_base"], 9300)

	@patch("hrms.regional.switzerland.payroll_hooks._get_component_insurance_flags")
	def test_no_flags_configured_fallback(self, mock_flags):
		"""When no component has flags configured, fall back to gross for all bases."""
		from hrms.regional.switzerland.payroll_hooks import _get_insurance_base_totals

		mock_flags.return_value = _component_fields(0, 0, 0, 0, 0, 0, wage_type=None)

		earnings = [
			self._make_earning_row("Basic", 8000),
			self._make_earning_row("Bonus", 2000),
		]
		doc = self._make_mock_doc(earnings)

		result = _get_insurance_base_totals(doc)

		# Backward compatibility: all bases = gross when no flags configured
		self.assertEqual(result["avs_base"], 10000)
		self.assertEqual(result["ac_base"], 10000)
		self.assertEqual(result["laa_base"], 10000)
		self.assertEqual(result["ijm_base"], 10000)
		self.assertEqual(result["lpp_base"], 10000)
		self.assertEqual(result["imp_base"], 10000)
		self.assertEqual(result["gross_total"], 10000)

	@patch("hrms.regional.switzerland.payroll_hooks._get_component_insurance_flags")
	def test_expense_not_in_any_base(self, mock_flags):
		"""Expenses (all flags = 0, has_flags=True) should not be in any insurance base."""
		from hrms.regional.switzerland.payroll_hooks import _get_insurance_base_totals

		def side_effect(comp):
			if comp == "Basic":
				return _component_fields(1, 1, 1, 1, 1, 1)
			elif comp == "Travel Expenses":
				# Explicitly configured as exempt from all
				return _component_fields(0, 0, 0, 0, 0, 0)
			return _component_fields(0, 0, 0, 0, 0, 0, wage_type=None)

		mock_flags.side_effect = side_effect

		earnings = [
			self._make_earning_row("Basic", 8000),
			self._make_earning_row("Travel Expenses", 500),
		]
		doc = self._make_mock_doc(earnings)

		result = _get_insurance_base_totals(doc)

		# Gross includes everything
		self.assertEqual(result["gross_total"], 8500)

		# But insurance bases only include Basic (8000)
		self.assertEqual(result["avs_base"], 8000)
		self.assertEqual(result["ac_base"], 8000)
		self.assertEqual(result["laa_base"], 8000)
		self.assertEqual(result["imp_base"], 8000)

	@patch("hrms.regional.switzerland.payroll_hooks._get_component_insurance_flags")
	def test_mix_configured_and_unconfigured(self, mock_flags):
		"""When some components have flags and some don't, unconfigured ones go into all bases."""
		from hrms.regional.switzerland.payroll_hooks import _get_insurance_base_totals

		def side_effect(comp):
			if comp == "Basic":
				return _component_fields(1, 1, 1, 1, 1, 1)
			elif comp in ("Travel Expenses", "Child Allowance"):
				# Explicitly exempt from everything
				return _component_fields(0, 0, 0, 0, 0, 0)
			else:
				# Not configured — goes into all bases
				return _component_fields(0, 0, 0, 0, 0, 0, wage_type=None)

		mock_flags.side_effect = side_effect

		earnings = [
			self._make_earning_row("Basic", 8000),
			self._make_earning_row("Child Allowance", 300),
			self._make_earning_row("Custom Bonus", 1000),  # unconfigured
		]
		doc = self._make_mock_doc(earnings)

		result = _get_insurance_base_totals(doc)

		# Custom Bonus (unconfigured) goes into all bases
		# AVS: Basic (8000) + Custom Bonus (1000) = 9000 (not Child Allowance)
		self.assertEqual(result["avs_base"], 9000)
		self.assertEqual(result["laa_base"], 9000)

		# Gross includes everything
		self.assertEqual(result["gross_total"], 9300)


class TestRateBasedComponentMapping(unittest.TestCase):
	"""Tests for the RATE_BASED_COMPONENTS mapping structure."""

	def test_all_entries_have_base_type(self):
		"""All RATE_BASED_COMPONENTS entries must have 3 elements including base_type."""
		from hrms.regional.switzerland.constants import RATE_BASED_COMPONENTS

		valid_bases = {"avs_base", "ac_base", "laa_base", "ijm_base", "lpp_base", "imp_base"}

		for comp_name, values in RATE_BASED_COMPONENTS.items():
			self.assertEqual(
				len(values),
				3,
				f"Component '{comp_name}' should have 3 values (rate_field, is_employer, base_type)",
			)
			rate_field, is_employer, base_type = values
			self.assertIn(
				base_type,
				valid_bases,
				f"Invalid base_type '{base_type}' for component '{comp_name}'",
			)
			self.assertIsInstance(is_employer, bool)
			self.assertIsInstance(rate_field, str)

	def test_avs_components_use_avs_base(self):
		"""AVS components should use avs_base."""
		from hrms.regional.switzerland.constants import RATE_BASED_COMPONENTS

		for comp_name in ("AVS/AI/APG Employee", "AVS/AI/APG Employer"):
			_, _, base_type = RATE_BASED_COMPONENTS[comp_name]
			self.assertEqual(base_type, "avs_base")

	def test_laa_components_use_laa_base(self):
		"""LAA components should use laa_base."""
		from hrms.regional.switzerland.constants import RATE_BASED_COMPONENTS

		for comp_name in ("LAA Professional Employer", "LAA Non-Professional Employee"):
			_, _, base_type = RATE_BASED_COMPONENTS[comp_name]
			self.assertEqual(base_type, "laa_base")

	def test_ijm_components_use_ijm_base(self):
		"""IJM components should use ijm_base."""
		from hrms.regional.switzerland.constants import RATE_BASED_COMPONENTS

		for comp_name in ("IJM/KTG Employee", "IJM/KTG Employer"):
			_, _, base_type = RATE_BASED_COMPONENTS[comp_name]
			self.assertEqual(base_type, "ijm_base")

	def test_family_allowances_use_avs_base(self):
		"""Family Allowances should use avs_base (same as AVS)."""
		from hrms.regional.switzerland.constants import RATE_BASED_COMPONENTS

		_, _, base_type = RATE_BASED_COMPONENTS["Family Allowances Employer"]
		self.assertEqual(base_type, "avs_base")


class TestComponentNames(unittest.TestCase):
	"""The payslip prints component names through _(): each one needs a catalogue entry."""

	def test_every_component_is_listed_for_the_catalogue(self):
		from hrms.regional.switzerland.setup import (
			COMPONENT_NAME_MESSAGES,
			get_swiss_salary_component_definitions,
		)

		listed = {message.msg for message in COMPONENT_NAME_MESSAGES}
		created = {definition["salary_component"] for definition in get_swiss_salary_component_definitions()}
		self.assertEqual(created - listed, set())

	def test_every_component_is_translated_to_french(self):
		"""A French payslip printed "AVS/AI/APG Employee" and "Source Tax Employee"."""
		from babel.messages.pofile import read_po

		import frappe

		from hrms.regional.switzerland.setup import COMPONENT_NAME_MESSAGES

		with open(frappe.get_app_path("hrms", "locale", "fr.po"), "rb") as po:
			catalog = read_po(po)
		missing = [
			message.msg
			for message in COMPONENT_NAME_MESSAGES
			if not (catalog.get(message.msg) and catalog.get(message.msg).string)
		]
		self.assertEqual(missing, [])


class TestEnsureSwissWageTypes(unittest.TestCase):
	"""after_migrate tops the catalogue up only where the Swiss payroll lives."""

	def topped_up(self, wage_types, swiss_components):
		from hrms.regional.switzerland import setup

		with (
			patch.object(setup.frappe.db, "table_exists", return_value=True),
			patch.object(setup.frappe.db, "count", return_value=wage_types),
			patch.object(setup.frappe.db, "exists", return_value=swiss_components),
			patch.object(setup, "create_swiss_wage_types") as create,
		):
			setup.ensure_swiss_wage_types()
		return create.called

	def test_a_site_without_the_swiss_payroll_gets_nothing(self):
		self.assertFalse(self.topped_up(0, False))

	def test_a_site_with_the_catalogue_is_topped_up(self):
		self.assertTrue(self.topped_up(180, False))

	def test_swiss_components_without_the_catalogue_get_it(self):
		# the components link to their wage type: it must exist before a new one is created
		self.assertTrue(self.topped_up(0, True))


if __name__ == "__main__":
	unittest.main()
