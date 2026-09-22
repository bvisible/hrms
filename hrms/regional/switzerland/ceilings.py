# //// Neoffice — added file (no upstream equivalent): insurance ceilings, cumulated pro rata temporis.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Insurance ceilings — AC, LAA, and the brackets of LAAC and IJM — as Swissdec computes them.

Swissdec guidelines, section 7.12:

* 7.12.1 — the contribution duration counts 30 days per month, from 1 January (or the
  entry) to 30 December (or the exit). A 31st, and the 28th or 29th of February, count
  as the 30th.
* 7.12.2 — a yearly limit is prorated to that duration:
  ((AM - EM) x 30 + AT - ET + 1) x (upper - lower) / 360. Entry 01.08, exit 31.12:
  150 days, 61'750 of the 148'200 UVG ceiling.
* 7.12.3 — "Periodische Vergütungen oder ein in der Höhe schwankender Lohn sind bei der
  Höchstlohnberechnung zu berücksichtigen": the CUMULATED insurance base is compared with
  the CUMULATED possible ceiling, and what the previous months of the year already insured
  is subtracted. What remains is the insured wage of the month.

Neither of the two shortcuts is the rule. "148'200 from January" charged a leaver in June
AC on 120'000 instead of 74'100. "12'350 every month" made a 13th month paid in December
lose the room the eleven months before it had left.

The previous months are taken as this same rule computed them, from their cumulated
bases and days (the difference of two cumulated amounts). The months of a year therefore
add up to the yearly result exactly, whatever the salaries did in between.

Pure module: no frappe.
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

YEAR_DAYS = 360
_CENT = Decimal("0.01")


def _day30(d):
	"""Day of the month on the 30-day basis of guidelines 7.12.1."""
	if d.day == 31 or (d.month == 2 and d.day >= 28):
		return 30
	return d.day


def contribution_days(start, end):
	"""Days from ``start`` to ``end`` inclusive, 30 per month (guidelines 7.12.1); 0 if end < start."""
	if not start or not end or end < start:
		return 0
	return (
		(end.year - start.year) * YEAR_DAYS + (end.month - start.month) * 30 + _day30(end) - _day30(start) + 1
	)


def contribution_period(entry, exit_date, period_start, period_end):
	"""(days before the period, days of the period) within the year of ``period_end``.

	Counted from 1 January or the entry, to the exit when there is one. A payment made after
	the exit gets no day of its own: it falls into the room the employment left (guidelines
	7.14.1, payments after exit in the current year).
	"""
	year_start = date(period_end.year, 1, 1)
	start = max(year_start, entry) if entry else year_start
	end_current = min(period_end, exit_date) if exit_date else period_end
	end_before = period_start - timedelta(days=1)
	if exit_date:
		end_before = min(end_before, exit_date)
	days_before = contribution_days(start, end_before) if end_before >= start else 0
	days_current = contribution_days(max(start, period_start), end_current)
	return days_before, days_current


def insured_between(cumulated_base, days, lower=0, upper=None):
	"""The part of a cumulated base insured between two YEARLY limits prorated to ``days``.

	``upper`` None or 0 means no upper limit. The prorated limits are rounded to the centime:
	148'200 x 61 / 360 = 25'111.666... is a ceiling of 25'111.67.
	"""
	base = Decimal(str(cumulated_base or 0))
	days = Decimal(int(days or 0))
	low = (Decimal(str(lower or 0)) * days / YEAR_DAYS).quantize(_CENT, rounding=ROUND_HALF_UP)
	part = base - low
	if upper:
		width = (Decimal(str(upper)) - Decimal(str(lower or 0))) * days / YEAR_DAYS
		part = min(part, width.quantize(_CENT, rounding=ROUND_HALF_UP))
	return max(part, Decimal(0))


def month_insured(ytd_base, days_before, base, days_current, lower=0, upper=None):
	"""Insured wage of the month under guidelines 7.12.3 (a float, to the centime).

	The cumulated insured wage at the end of the month, minus the cumulated insured wage at
	the end of the month before. It can be negative when the base is: a salary correction
	gives back what it had insured.
	"""
	before = insured_between(ytd_base, days_before, lower, upper)
	now = insured_between(
		Decimal(str(ytd_base or 0)) + Decimal(str(base or 0)),
		int(days_before or 0) + int(days_current or 0),
		lower,
		upper,
	)
	return float((now - before).quantize(_CENT, rounding=ROUND_HALF_UP))
