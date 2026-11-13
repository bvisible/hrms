# //// Neoffice — added file (no upstream equivalent): the HR manager corrects a day's clock, with a reason; the engine
# //// reads the correction in place of the check-ins and never changes them (lot T, neoffice-maintenance#2623).
"""A day's clock corrected by the HR manager, with its reason.

The check-ins stay as the clock wrote them. `correct_day` writes a correction (the day's intervals before and after,
the reason, who and when) and records the week again: its hours done follow the correction, and an approval of its
hours over is withdrawn when they change. The latest correction of a day is the one the engine reads
(`corrected_days`): its intervals replace the clock's for the hours done and for the supplements of a time range. A
correction without a reason is refused; only who may create a correction (the HR manager) corrects.
"""

import datetime
import json
from itertools import pairwise

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime

CORRECTION_DOCTYPE = "Working Time Correction"


def _minutes(value: str) -> int:
	hours, _, minutes = str(value).strip().partition(":")
	return int(hours) * 60 + int(minutes or 0)


def _checked(intervals) -> list:
	"""The day's intervals as [["HH:MM", "HH:MM"], …], each ending after it starts, in order and apart."""
	if isinstance(intervals, str):
		intervals = json.loads(intervals or "[]")
	cleaned = []
	for pair in intervals or []:
		start, end = (str(pair[0]).strip(), str(pair[1]).strip())
		try:
			first, last = _minutes(start), _minutes(end)
		except ValueError:
			frappe.throw(_("Write each time as HH:MM."))
		if not (0 <= first < last <= 24 * 60):
			frappe.throw(_("An interval ends after it starts, within the day: {0} – {1}.").format(start, end))
		cleaned.append((first, last, start, end))
	cleaned.sort()
	for previous, following in pairwise(cleaned):
		if following[0] < previous[1]:
			frappe.throw(_("Two intervals of the day overlap."))
	return [[start, end] for _first, _last, start, end in cleaned]


def _hours(intervals) -> float:
	return round(sum(_minutes(end) - _minutes(start) for start, end in intervals) / 60, 4)


@frappe.whitelist()
def correct_day(employee: str, day, intervals, reason: str) -> dict:
	"""The HR manager corrects the clock of an employee's day; the week is recorded again from it."""
	from hrms.hr.working_time.store import record_week
	from hrms.hr.working_time.supplements import worked_intervals

	frappe.has_permission(CORRECTION_DOCTYPE, "create", throw=True)
	frappe.get_doc("Employee", employee).check_permission("read")
	if not (reason or "").strip():
		frappe.throw(_("Say why the clock is corrected: the reason stays with the correction."))
	day = getdate(day)
	after = _checked(intervals)
	before = [
		[f"{start:%H:%M}", f"{end:%H:%M}"]
		for start, end in worked_intervals(employee, day, day)
		if start.date() == day
	]
	doc = frappe.get_doc(
		{
			"doctype": CORRECTION_DOCTYPE,
			"employee": employee,
			"day": day,
			"before": json.dumps(before),
			"after": json.dumps(after),
			"hours_before": _hours(before),
			"hours_after": _hours(after),
			"reason": reason.strip(),
			"corrected_by": frappe.session.user,
			"corrected_on": now_datetime(),
		}
	)
	doc.insert(ignore_permissions=True)
	week = record_week(employee, day)
	return {"correction": doc.name, "week": week, "hours": doc.hours_after}


def corrected_days(employee: str, first, last) -> dict:
	"""{day: {"intervals", "hours", "reason", "by", "on"}}: the latest correction of each day from `first` to `last`."""
	found = {}
	for row in frappe.get_all(
		CORRECTION_DOCTYPE,
		filters={"employee": employee, "day": ["between", [getdate(first), getdate(last)]]},
		fields=["day", "after", "hours_after", "reason", "corrected_by", "corrected_on"],
		order_by="corrected_on asc, creation asc",
	):
		found[getdate(row.day)] = {
			"intervals": json.loads(row.after or "[]"),
			"hours": row.hours_after,
			"reason": row.reason,
			"by": row.corrected_by,
			"on": row.corrected_on,
		}
	return found


def as_datetimes(day, intervals) -> list:
	"""A day's intervals as (start, end) moments."""
	day = getdate(day)
	base = datetime.datetime.combine(day, datetime.time())
	return [
		(base + datetime.timedelta(minutes=_minutes(start)), base + datetime.timedelta(minutes=_minutes(end)))
		for start, end in intervals
	]
