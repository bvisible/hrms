# //// Neoffice — added file (no upstream equivalent): unit tests of the Employee -> certified Odoo
# //// contract mapping.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest

from hrms.regional.switzerland.odoo_employee_map import activity_fields


class TestActivityFields(unittest.TestCase):
	"""The activity at other employers as the certified engine reads it (#839): the same fields the
	bench set on its contracts to agree to the centime."""

	def test_one_employer(self):
		fields = activity_fields({"ch_work_percentage": 50})
		self.assertEqual(fields["l10n_ch_current_occupation_rate"], 50)
		self.assertIs(fields["l10n_ch_other_employment"], False)
		self.assertIs(fields["l10n_ch_total_activity_type"], False)
		self.assertIs(fields["irregular_working_time"], False)

	def test_full_time_when_no_rate_is_recorded(self):
		self.assertEqual(activity_fields({})["l10n_ch_current_occupation_rate"], 100)

	def test_other_employers_unknown(self):
		fields = activity_fields(
			{"ch_work_percentage": 50, "ch_qst_other_employment": 1, "ch_qst_other_activity_basis": "Unknown"}
		)
		self.assertEqual(
			(fields["l10n_ch_other_employment"], fields["l10n_ch_total_activity_type"]), (True, "unknown")
		)

	def test_only_the_figure_of_what_is_known_is_sent(self):
		employee = {
			"ch_work_percentage": 50,
			"ch_qst_other_employment": 1,
			"ch_qst_other_activity_rate": 30,
			"ch_qst_other_activity_gross": 4000,
		}
		rate = activity_fields({**employee, "ch_qst_other_activity_basis": "Work Percentage"})
		self.assertEqual(
			(
				rate["l10n_ch_total_activity_type"],
				rate["l10n_ch_other_activity_percentage"],
				rate["l10n_ch_other_activity_gross"],
			),
			("percentage", 30, 0),
		)
		gross = activity_fields({**employee, "ch_qst_other_activity_basis": "Gross Income"})
		self.assertEqual(
			(
				gross["l10n_ch_total_activity_type"],
				gross["l10n_ch_other_activity_percentage"],
				gross["l10n_ch_other_activity_gross"],
			),
			("gross", 0, 4000),
		)
