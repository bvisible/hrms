# //// Neoffice — added file (no upstream equivalent): unit tests of the ESTV fixed-width parser.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest
from unittest.mock import patch  # //// Neoffice — added, used by the last class of the file.

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
		line = "0601ZHA0N       20260101000000100000080000 0000000123450025   "
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


# //// Neoffice — added: the fields below used to fall back to 0.0 when they could not be read,
# //// which in this file is not a fallback but a wrong tariff — a bracket that withholds nothing.
class TestCorruptRecordsAreNotImportedAsZero(unittest.TestCase):
	"""A bracket we cannot read is dropped, never imported as a bracket worth zero."""

	# Same layout as SAMPLE_LINE_06, with one field replaced by something unreadable.
	BAD_TAX_AMOUNT = "0601ZHA0N       20260101000000100000080000 00XXXXXXXX0025   "
	BAD_TAX_RATE = "0601ZHA0N       20260101000000100000080000 0000000000000X2X   "
	BAD_INCOME_FROM = "0601ZHA0N       2026010100000010X000080000 0000000000000025   "
	BAD_CHILDREN = "0601ZHA0N       20260101000000100000080000 XX00000000000025   "

	def test_unreadable_tax_amount_is_not_a_bracket_worth_zero(self):
		"""It used to return tax_amount 0.0 — an income band withheld nothing."""
		self.assertIsNone(parse_line(self.BAD_TAX_AMOUNT))

	def test_unreadable_tax_rate_is_not_a_zero_rate(self):
		self.assertIsNone(parse_line(self.BAD_TAX_RATE))

	def test_unreadable_income_from_is_not_a_bracket_starting_at_zero(self):
		"""income_from 0.0 shadows the real first bracket of the tariff."""
		self.assertIsNone(parse_line(self.BAD_INCOME_FROM))

	def test_unreadable_children_count_is_not_zero_children(self):
		self.assertIsNone(parse_line(self.BAD_CHILDREN))

	def test_a_blank_children_field_is_still_zero_children(self):
		"""Blank is a legitimate absence, not corruption — this must keep parsing."""
		blank_children = SAMPLE_LINE_06[:43] + "  " + SAMPLE_LINE_06[45:]
		result = parse_line(blank_children)
		self.assertIsNotNone(result)
		self.assertEqual(result["num_children"], 0)

	def test_a_real_zero_amount_is_still_a_bracket(self):
		"""Witness: 0 written in the file is a real zero and must survive."""
		result = parse_line(SAMPLE_LINE_06)
		self.assertIsNotNone(result)
		self.assertEqual(result["tax_amount"], 0.0)

	def test_the_dropped_records_are_reported(self):
		"""A hole in a cantonal withholding table cannot be silent."""
		content = f"{SAMPLE_LINE_06}\n{self.BAD_TAX_AMOUNT}\n{SAMPLE_LINE_HEADER}"
		with patch("frappe.log_error") as log_error:
			brackets = parse_estv_tariff_file(content)
		self.assertEqual(len(brackets), 1)
		log_error.assert_called_once()
		self.assertIn("1 type 06 record", log_error.call_args[0][1])

	def test_a_clean_file_reports_nothing(self):
		"""And a file with nothing wrong must not cry wolf."""
		content = f"{SAMPLE_LINE_06}\n{SAMPLE_LINE_HIGH_INCOME}\n{SAMPLE_LINE_HEADER}"
		with patch("frappe.log_error") as log_error:
			brackets = parse_estv_tariff_file(content)
		self.assertEqual(len(brackets), 2)
		log_error.assert_not_called()


if __name__ == "__main__":
	unittest.main()
