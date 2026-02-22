# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest

from hrms.regional.switzerland.estv_parser import parse_estv_tariff_file, parse_line


# Sample lines from real ESTV files (ZH 2026) — exactly 62 chars each
# Format: [0:2]type [2:4]txn [4:6]canton [6:9]code [9:16]spaces [16:24]date
#         [24:33]income_rappen(9) [33:42]step_rappen(9) [42]space
#         [43:45]children(2) [45:55]tax_amount_rappen(10) [55:59]rate_hundredths(4) [59:62]pad
SAMPLE_LINE_06 = "0601ZHA0N       20260101000000100000080000 0000000000000025   "
SAMPLE_LINE_HEADER = "0101ZH                                                        "
SAMPLE_LINE_HIGH_INCOME = "0601ZHB2Y       20260101000500100000005000 0200000000001250   "


class TestParseLine(unittest.TestCase):
	"""Tests for individual line parsing."""

	def test_parse_type_06_record(self):
		"""Type 06 record is parsed correctly."""
		result = parse_line(SAMPLE_LINE_06)
		self.assertIsNotNone(result)
		self.assertEqual(result["canton"], "ZH")
		self.assertEqual(result["tariff_code"], "A0N")
		self.assertAlmostEqual(result["income_from"], 1.0, places=2)
		self.assertAlmostEqual(result["income_step"], 800.0, places=2)
		self.assertEqual(result["num_children"], 0)
		self.assertAlmostEqual(result["tax_amount"], 0.0, places=2)
		self.assertAlmostEqual(result["tax_rate"], 0.0025, places=6)

	def test_parse_non_06_record_returns_none(self):
		"""Non-type-06 records return None."""
		result = parse_line(SAMPLE_LINE_HEADER)
		self.assertIsNone(result)

	def test_parse_short_line_returns_none(self):
		"""Lines shorter than 59 chars return None."""
		result = parse_line("06")
		self.assertIsNone(result)

	def test_parse_empty_line_returns_none(self):
		"""Empty lines return None."""
		result = parse_line("")
		self.assertIsNone(result)

	def test_rappen_to_chf_conversion(self):
		"""Income amounts are correctly converted from Rappen to CHF."""
		result = parse_line(SAMPLE_LINE_HIGH_INCOME)
		self.assertIsNotNone(result)
		# 000500100 Rappen = 5001.00 CHF
		self.assertAlmostEqual(result["income_from"], 5001.0, places=2)
		# 000005000 Rappen = 50.00 CHF
		self.assertAlmostEqual(result["income_step"], 50.0, places=2)

	def test_rate_conversion(self):
		"""Tax rate is correctly converted from 0.01% units to decimal."""
		result = parse_line(SAMPLE_LINE_HIGH_INCOME)
		self.assertIsNotNone(result)
		# 1250 in 0.01% units = 12.50% = 0.1250 decimal
		self.assertAlmostEqual(result["tax_rate"], 0.125, places=6)

	def test_tariff_code_with_children(self):
		"""Tariff code with children is parsed correctly."""
		result = parse_line(SAMPLE_LINE_HIGH_INCOME)
		self.assertEqual(result["tariff_code"], "B2Y")
		self.assertEqual(result["num_children"], 2)

	def test_valid_from_date(self):
		"""Valid from date is parsed as ISO string."""
		result = parse_line(SAMPLE_LINE_06)
		self.assertEqual(result["valid_from"], "2026-01-01")

	def test_tax_amount_rappen_conversion(self):
		"""Tax amount is correctly converted from Rappen to CHF."""
		# Construct a line with a non-zero tax amount: 0000012345 Rappen = 123.45 CHF
		line = "0601ZHA0N       20260101000000100000080000 0000001234500025   "
		result = parse_line(line)
		self.assertAlmostEqual(result["tax_amount"], 123.45, places=2)


class TestParseFile(unittest.TestCase):
	"""Tests for full file parsing."""

	def test_parse_multiple_lines(self):
		"""Multiple type 06 lines are all parsed."""
		content = f"{SAMPLE_LINE_06}\n{SAMPLE_LINE_HIGH_INCOME}\n{SAMPLE_LINE_HEADER}"
		brackets = parse_estv_tariff_file(content)
		self.assertEqual(len(brackets), 2)

	def test_canton_filter(self):
		"""Canton filter excludes non-matching lines."""
		line_ge = "0601GEA0N       20260101000000100000244995 0000000000000000   "
		content = f"{SAMPLE_LINE_06}\n{line_ge}"
		brackets = parse_estv_tariff_file(content, canton="GE")
		self.assertEqual(len(brackets), 1)
		self.assertEqual(brackets[0]["canton"], "GE")

	def test_bytes_input(self):
		"""Bytes input (Latin-1 encoded) is handled correctly."""
		content = SAMPLE_LINE_06.encode("latin-1")
		brackets = parse_estv_tariff_file(content)
		self.assertEqual(len(brackets), 1)

	def test_empty_content(self):
		"""Empty content returns empty list."""
		brackets = parse_estv_tariff_file("")
		self.assertEqual(brackets, [])


if __name__ == "__main__":
	unittest.main()
