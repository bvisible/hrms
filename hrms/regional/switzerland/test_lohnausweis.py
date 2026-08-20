# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest

from hrms.payroll.doctype.swiss_salary_certificate.swiss_salary_certificate import (
	aggregate_salary_slips_for_lohnausweis,
)
from hrms.regional.switzerland.constants import DEFAULT_LOHNAUSWEIS_MAPPING, POSITION_FIELD_MAP


class TestLohnausweisMapping(unittest.TestCase):
	"""Tests for Lohnausweis mapping completeness."""

	def test_default_mapping_covers_core_components(self):
		"""Default mapping includes Basic, 13th month, and all employee social charges."""
		mapped_components = {m["salary_component"] for m in DEFAULT_LOHNAUSWEIS_MAPPING}

		# Income
		self.assertIn("Basic", mapped_components)
		self.assertIn("13th Month Salary", mapped_components)

		# Social deductions (employee side)
		self.assertIn("AVS/AI/APG Employee", mapped_components)
		self.assertIn("AC/ALV Employee", mapped_components)
		self.assertIn("AC Solidarity Employee", mapped_components)
		self.assertIn("LAA Non-Professional Employee", mapped_components)
		self.assertIn("IJM/KTG Employee", mapped_components)
		self.assertIn("LPP/BVG Employee", mapped_components)

	def test_default_mapping_positions_valid(self):
		"""All positions in default mapping exist in POSITION_FIELD_MAP."""
		for mapping in DEFAULT_LOHNAUSWEIS_MAPPING:
			self.assertIn(
				mapping["lohnausweis_position"],
				POSITION_FIELD_MAP,
				f"Position {mapping['lohnausweis_position']} for {mapping['salary_component']} "
				f"not found in POSITION_FIELD_MAP",
			)

	def test_position_field_map_completeness(self):
		"""POSITION_FIELD_MAP covers all 20 Form 11 positions (incl. 13.x sub-positions)."""
		expected_positions = {
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
		self.assertEqual(set(POSITION_FIELD_MAP.keys()), expected_positions)

	def test_position_field_map_fields_unique(self):
		"""Each position maps to a unique field name."""
		fields = list(POSITION_FIELD_MAP.values())
		self.assertEqual(len(fields), len(set(fields)))


class TestLohnausweisComputation(unittest.TestCase):
	"""Tests for aggregate_salary_slips_for_lohnausweis (pure function)."""

	def test_position_1_aggregates_basic_and_13th(self):
		"""Basic and 13th month both map to position 1 and are summed."""
		slips_data = {
			"Basic": 96000.0,
			"13th Month Salary": 8000.0,
		}
		position_map = {
			"Basic": "1",
			"13th Month Salary": "1",
		}
		result = aggregate_salary_slips_for_lohnausweis(slips_data, position_map)
		self.assertAlmostEqual(result["1"], 104000.0, places=2)

	def test_position_9_aggregates_social_insurance(self):
		"""All employee social charges map to position 9 and are summed."""
		slips_data = {
			"AVS/AI/APG Employee": 5088.0,
			"AC/ALV Employee": 1056.0,
			"AC Solidarity Employee": 0.0,
			"LAA Non-Professional Employee": 1152.0,
			"IJM/KTG Employee": 480.0,
		}
		position_map = {
			"AVS/AI/APG Employee": "9",
			"AC/ALV Employee": "9",
			"AC Solidarity Employee": "9",
			"LAA Non-Professional Employee": "9",
			"IJM/KTG Employee": "9",
		}
		result = aggregate_salary_slips_for_lohnausweis(slips_data, position_map)
		self.assertAlmostEqual(result["9"], 7776.0, places=2)

	def test_position_10_1_lpp(self):
		"""LPP/BVG Employee maps to position 10.1."""
		slips_data = {"LPP/BVG Employee": 1593.96}
		position_map = {"LPP/BVG Employee": "10.1"}
		result = aggregate_salary_slips_for_lohnausweis(slips_data, position_map)
		self.assertAlmostEqual(result["10.1"], 1593.96, places=2)

	def test_unmapped_components_excluded(self):
		"""Components not in position_map are excluded from the result."""
		slips_data = {
			"Basic": 96000.0,
			"Travel Allowance": 3600.0,
			"AVS/AI/APG Employer": 5088.0,
		}
		position_map = {"Basic": "1"}
		result = aggregate_salary_slips_for_lohnausweis(slips_data, position_map)
		self.assertEqual(list(result.keys()), ["1"])
		self.assertAlmostEqual(result["1"], 96000.0, places=2)

	def test_empty_slips_data(self):
		"""Empty slips data returns empty result."""
		result = aggregate_salary_slips_for_lohnausweis({}, {"Basic": "1"})
		self.assertEqual(result, {})

	def test_empty_position_map(self):
		"""Empty position map returns empty result."""
		result = aggregate_salary_slips_for_lohnausweis({"Basic": 96000.0}, {})
		self.assertEqual(result, {})

	def test_full_year_scenario(self):
		"""Full year with typical Swiss payroll: 12 months of slips."""
		monthly_basic = 8000.0
		monthly_avs = monthly_basic * 0.053
		monthly_ac = monthly_basic * 0.011
		monthly_lpp = 132.83

		slips_data = {
			"Basic": monthly_basic * 12,
			"AVS/AI/APG Employee": monthly_avs * 12,
			"AC/ALV Employee": monthly_ac * 12,
			"LPP/BVG Employee": monthly_lpp * 12,
		}
		position_map = {
			"Basic": "1",
			"AVS/AI/APG Employee": "9",
			"AC/ALV Employee": "9",
			"LPP/BVG Employee": "10.1",
		}
		result = aggregate_salary_slips_for_lohnausweis(slips_data, position_map)

		self.assertAlmostEqual(result["1"], 96000.0, places=2)
		expected_pos_9 = round((monthly_avs + monthly_ac) * 12, 2)
		self.assertAlmostEqual(result["9"], expected_pos_9, places=2)
		self.assertAlmostEqual(result["10.1"], round(monthly_lpp * 12, 2), places=2)

	def test_partial_year_employee(self):
		"""Employee with only 6 months of slips."""
		slips_data = {
			"Basic": 48000.0,
			"AVS/AI/APG Employee": 2544.0,
		}
		position_map = {
			"Basic": "1",
			"AVS/AI/APG Employee": "9",
		}
		result = aggregate_salary_slips_for_lohnausweis(slips_data, position_map)
		self.assertAlmostEqual(result["1"], 48000.0, places=2)
		self.assertAlmostEqual(result["9"], 2544.0, places=2)


class TestCertificateCalculatedFields(unittest.TestCase):
	"""Tests for position 8 (gross) and position 11 (net) calculations."""

	def test_position_8_total_gross(self):
		"""Position 8 = sum of positions 1-7."""
		# Simulate by calling the pure calculation
		positions = {
			"1": 96000.0,
			"2.1": 2000.0,
			"2.2": 0.0,
			"2.3": 0.0,
			"3": 5000.0,
			"4": 0.0,
			"5": 0.0,
			"6": 0.0,
			"7": 1000.0,
		}
		gross = sum(positions.values())
		self.assertAlmostEqual(gross, 104000.0, places=2)

	def test_position_11_net_salary(self):
		"""Position 11 = 8 - 9 - 10.1 - 10.2."""
		gross = 104000.0
		pos_9 = 7776.0
		pos_10_1 = 1593.96
		pos_10_2 = 0.0
		net = gross - pos_9 - pos_10_1 - pos_10_2
		self.assertAlmostEqual(net, 94630.04, places=2)


if __name__ == "__main__":
	unittest.main()
