# //// Neoffice — added file (no upstream equivalent): controller of the Cross Border Telework Log.
# //// Frontalier status (DE/FR/IT) is lost beyond a telework/non-return threshold, so the
# //// days have to be logged per employee and year.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class CrossBorderTeleworkLog(Document):
	def validate(self):
		self._validate_days()
		self._calculate_telework_pct()
		self._calculate_ytd_totals()
		self._check_threshold()

	def _validate_days(self):
		"""Ensure telework days do not exceed total work days."""
		if cint(self.telework_days) > cint(self.total_work_days):
			frappe.throw(
				_("Telework days ({0}) cannot exceed total work days ({1}).").format(
					self.telework_days, self.total_work_days
				)
			)

		if cint(self.telework_days) < 0:
			frappe.throw(_("Telework days cannot be negative."))

		if cint(self.total_work_days) < 0:
			frappe.throw(_("Total work days cannot be negative."))

	def _calculate_telework_pct(self):
		"""Calculate telework percentage for this month."""
		total = cint(self.total_work_days)
		if total > 0:
			self.telework_pct = flt(cint(self.telework_days) / total * 100, 2)
		else:
			self.telework_pct = 0

	def _calculate_ytd_totals(self):
		"""Calculate YTD cumulative totals from previous months in the same year."""
		prev_totals = get_ytd_telework_totals(
			self.employee, self.year, self.month, exclude=self.name
		)

		ytd_telework = prev_totals["total_telework_days"] + cint(self.telework_days)
		ytd_work = prev_totals["total_work_days"] + cint(self.total_work_days)
		ytd_assignment = prev_totals["total_assignment_days"] + cint(self.assignment_days)
		ytd_non_return = prev_totals["total_non_return_days"] + cint(self.non_return_days)

		self.ytd_telework_pct = flt(ytd_telework / ytd_work * 100, 2) if ytd_work > 0 else 0
		self.ytd_assignment_days = ytd_assignment
		self.ytd_non_return_days = ytd_non_return

	def _check_threshold(self):
		"""Set threshold warning if YTD telework exceeds configured threshold."""
		config = _get_config(self.company)
		threshold = flt(config.get("cb_french_telework_threshold") if config else 0) or 40

		self.threshold_warning = 1 if flt(self.ytd_telework_pct) > threshold else 0


def get_ytd_telework_totals(employee, year, current_month, exclude=None):
	"""Get YTD cumulative telework totals for months before current_month.

	Args:
		employee: Employee ID.
		year: Calendar year.
		current_month: Current month number (1-12). Only sums months < this.
		exclude: Document name to exclude (for re-validation of existing record).

	Returns:
		dict with total_telework_days, total_work_days, total_assignment_days,
		total_non_return_days.
	"""
	# //// Neoffice — was `("<", str(cint(current_month)))`. month is a Select, so the column is
	# //// a VARCHAR and MariaDB compared the STRINGS: from October on, "2".."9" are greater than
	# //// "10" and every month from February to September fell out of the year-to-date total.
	# //// The telework percentage it feeds is what decides whether a frontalier keeps his status,
	# //// so an employee over the threshold looked well under it for the last quarter of the year.
	# //// An explicit list of the prior months instead of a comparison — it also survives a
	# //// Postgres site, which refuses to compare a text column to a number at all.
	prior_months = [str(month) for month in range(1, cint(current_month))]
	if not prior_months:
		return _empty_totals()

	filters = {
		"employee": employee,
		"year": cint(year),
		# //// Neoffice — an explicit list, see above: "<" on this Select compared strings.
		"month": ("in", prior_months),
		"docstatus": 1,
	}

	if exclude:
		filters["name"] = ("!=", exclude)

	result = frappe.db.get_all(
		"Cross-Border Telework Log",
		filters=filters,
		fields=[
			"sum(telework_days) as total_telework_days",
			"sum(total_work_days) as total_work_days",
			"sum(assignment_days) as total_assignment_days",
			"sum(non_return_days) as total_non_return_days",
		],
	)

	if result:
		return {
			"total_telework_days": cint(result[0].get("total_telework_days")),
			"total_work_days": cint(result[0].get("total_work_days")),
			"total_assignment_days": cint(result[0].get("total_assignment_days")),
			"total_non_return_days": cint(result[0].get("total_non_return_days")),
		}

	return _empty_totals()


# //// Neoffice — extracted with the month-comparison fix above, so the early return for January
# //// gives the same shape as the query.
def _empty_totals():
	"""The zero totals, for a month with nothing before it."""
	return {
		"total_telework_days": 0,
		"total_work_days": 0,
		"total_assignment_days": 0,
		"total_non_return_days": 0,
	}


def _get_config(company):
	"""Fetch Swiss Social Insurance Config for a company."""
	from hrms.regional.switzerland.utils import get_swiss_social_insurance_config

	return get_swiss_social_insurance_config(company)
