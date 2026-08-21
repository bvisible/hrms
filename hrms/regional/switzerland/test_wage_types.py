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
		"""APG (2000) should be subject to AVS+AC+IMP only."""
		wt = self._get_by_code("2000")
		self.assertEqual(wt["subject_to_avs"], 1)
		self.assertEqual(wt["subject_to_ac"], 1)
		self.assertEqual(wt["subject_to_laa"], 0)
		self.assertEqual(wt["subject_to_ijm"], 0)
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
				wt[f] for f in ["subject_to_avs", "subject_to_ac", "subject_to_laa",
								"subject_to_ijm", "subject_to_lpp", "subject_to_imp"]
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
					wt[f] for f in ["subject_to_avs", "subject_to_ac", "subject_to_laa",
									"subject_to_ijm", "subject_to_lpp", "subject_to_imp"]
				)
				self.assertEqual(
					total_flags,
					0,
					f"Deduction {wt['code']} ({wt['wage_type_name']}) should have 0 flags, got {total_flags}",
				)

	def test_lohnausweis_positions_valid(self):
		"""All lohnausweis_position values should be from the valid set."""
		valid_positions = {
			"", "1", "2.1", "2.2", "2.3", "3", "4", "5", "6", "7",
			"9", "10.1", "10.2", "12",
			"13.1.1", "13.1.2", "13.2.1", "13.2.2", "13.2.3", "14",
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

		mock_flags.return_value = {
			"avs": 1, "ac": 1, "laa": 1, "ijm": 1, "lpp": 1, "imp": 1,
			"has_flags": True,
		}

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
				return {"avs": 1, "ac": 1, "laa": 1, "ijm": 1, "lpp": 1, "imp": 1, "has_flags": True}
			elif comp == "Child Allowance":
				# Exempt from social charges but subject to source tax
				return {"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 1, "has_flags": True}
			elif comp == "APG Allowance":
				return {"avs": 1, "ac": 1, "laa": 0, "ijm": 0, "lpp": 0, "imp": 1, "has_flags": True}
			return {"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0, "has_flags": False}

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

		mock_flags.return_value = {
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
			"has_flags": False,
		}

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
				return {"avs": 1, "ac": 1, "laa": 1, "ijm": 1, "lpp": 1, "imp": 1, "has_flags": True}
			elif comp == "Travel Expenses":
				# Explicitly configured as exempt from all
				return {"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0, "has_flags": True}
			return {"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0, "has_flags": False}

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
				return {"avs": 1, "ac": 1, "laa": 1, "ijm": 1, "lpp": 1, "imp": 1, "has_flags": True}
			elif comp in ("Travel Expenses", "Child Allowance"):
				# Explicitly exempt from everything
				return {"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0, "has_flags": True}
			else:
				# Not configured — goes into all bases
				return {"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0, "has_flags": False}

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


class TestDefaultLohnausweisMapping(unittest.TestCase):
	"""Tests for the DEFAULT_LOHNAUSWEIS_MAPPING constant."""

	def test_all_entries_have_required_fields(self):
		"""Each mapping entry must have salary_component and lohnausweis_position."""
		from hrms.regional.switzerland.constants import DEFAULT_LOHNAUSWEIS_MAPPING

		for entry in DEFAULT_LOHNAUSWEIS_MAPPING:
			self.assertIn("salary_component", entry)
			self.assertIn("lohnausweis_position", entry)
			self.assertTrue(entry["salary_component"])
			self.assertTrue(entry["lohnausweis_position"])

	def test_no_duplicate_components(self):
		"""Each component should appear at most once in the mapping."""
		from hrms.regional.switzerland.constants import DEFAULT_LOHNAUSWEIS_MAPPING

		components = [entry["salary_component"] for entry in DEFAULT_LOHNAUSWEIS_MAPPING]
		self.assertEqual(len(components), len(set(components)), "Duplicate components in mapping")

	def test_new_earning_components_present(self):
		"""All new earning components should be in the mapping."""
		from hrms.regional.switzerland.constants import DEFAULT_LOHNAUSWEIS_MAPPING

		comp_names = {entry["salary_component"] for entry in DEFAULT_LOHNAUSWEIS_MAPPING}
		expected = {
			"Basic",
			"13th Month Salary",
			"Overtime Pay",
			"Vacation Allowance",
			"Bonus",
			"APG Allowance",
			"IJM Sickness Allowance",
			"Maternity Allowance",
			"Child Allowance",
			"Travel Expenses",
			"Car Expenses",
			"Meal Expenses",
			"Flat-Rate Representation Expenses",
		}
		missing = expected - comp_names
		self.assertEqual(missing, set(), f"Missing components in mapping: {missing}")


if __name__ == "__main__":
	unittest.main()
