# //// Neoffice — added file (no upstream equivalent): the year-end closing's recap, as the desk page reads it.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

from datetime import date
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from hrms.regional.switzerland import year_end


class TestYearEndRecap(FrappeTestCase):
	def test_a_year_without_slips_answers_the_shape_the_page_reads(self):  # role-check: ok it only reads
		"""The page stopped on `counts` and stayed blank after « Reconcile » for a year without submitted slips."""
		with (
			patch.object(year_end, "_check_payroll_read_permission"),
			patch.object(
				year_end, "_fiscal_year_bounds", return_value=(date(2025, 1, 1), date(2025, 12, 31))
			),
			patch.object(year_end, "_slips_of_year", return_value=[]),
		):
			recap = year_end.reconcile("_Test Company", "2025")

		self.assertEqual(recap["employees"], [])
		self.assertEqual(recap["period"], {"start": "2025-01-01", "end": "2025-12-31"})
		self.assertEqual(
			recap["counts"],
			{
				"employees": 0,
				"certificates_missing": 0,
				"certificates_draft": 0,
				"certificates_submitted": 0,
				"certificates_sent": 0,
			},
		)
		self.assertEqual([issue["level"] for issue in recap["issues"]], ["warning"])
