# //// Neoffice — added file (no upstream equivalent): the supplements of the hours worked in the agreement's
# //// time ranges (night, Saturday, Sunday, public holidays), read from the clock (lot T, neoffice-maintenance#2623).
"""The supplements by time range: which hours worked fall in which range of the agreement, at which rate.

The agreement's table (`time_range_supplements`, confirmed by the client) gives each range: its days of the week
(1 = Monday … 7 = Sunday), its hours (`from`, `to`; a range that ends before it starts runs past midnight, into
the next day), its months, whether it is a public holiday's (`day_type`), and a rate in per cent or an amount per
hour. Every minute worked is set against every range:

- without cumulation (`supplements_cumulate` not confirmed true), a minute takes the highest rate that applies; an
  amount per hour applies only where no rate does (a night allowance is never paid on top of a night rate), and
  a rate of 0 % gives nothing;
- with cumulation, every range that applies counts.

A row the company does not use (night work of more than a week, say, where the agreement gives three kinds of
night work) is taken out of the table by the client before confirming it: the engine applies every confirmed row.

`supplement_lines` is pure: the intervals worked and the days that are public holidays come in, one line per day
and range comes out (`date`, `label`, `article`, `hours`, `percent`, `amount_per_hour`). Turning a line into money
is the payroll's: the hourly wage is the monthly one divided by the agreement's `hourly_divisor`.
`worked_intervals` reads the intervals of an employee from their check-ins (an IN, then the next OUT), or from the
attendance's in and out times when there are none; a day the HR manager corrected is read from its correction.
"""

import datetime
from collections import defaultdict

from frappe.utils import flt, get_datetime, getdate

MINUTES_A_DAY = 24 * 60


def _minutes(value) -> int:
	"""'HH:MM' as minutes since midnight; '24:00' is the end of the day."""
	hours, _, minutes = str(value).partition(":")
	return int(hours) * 60 + int(minutes or 0)


def _matches(row, moment: datetime.datetime, holidays) -> bool:
	"""Whether the minute that starts at `moment` falls in the range of `row`."""
	day = moment.date()
	if row.get("months") and moment.month not in row["months"]:
		return False
	if row.get("day_type") == "public_holiday" and holidays.get(day) != "holiday":
		return False
	weekdays = row.get("weekdays") or range(1, 8)
	start = _minutes(row.get("from") or "00:00")
	end = _minutes(row.get("to") or "24:00")
	now = moment.hour * 60 + moment.minute
	if start <= end:
		return day.isoweekday() in weekdays and start <= now < end
	yesterday = (day - datetime.timedelta(days=1)).isoweekday()
	return (now >= start and day.isoweekday() in weekdays) or (now < end and yesterday in weekdays)


def _applying(table, indexes, cumulate: bool) -> list:
	"""The rows (by index) that count for one minute, among those whose range it falls in."""
	rated = [index for index in indexes if flt(table[index].get("percent")) > 0]
	paid = [index for index in indexes if flt(table[index].get("amount_per_hour")) > 0]
	if cumulate:
		return sorted(set(rated) | set(paid))
	if rated:
		return [max(rated, key=lambda index: flt(table[index].get("percent")))]
	return [max(paid, key=lambda index: flt(table[index].get("amount_per_hour")))] if paid else []


def supplement_lines(rules, intervals, holidays=None) -> list:
	"""One line per day and range for the minutes worked in `intervals` ([(start, end), …]); [] without a table."""
	table = rules.get("time_range_supplements") or []
	if not table:
		return []
	holidays = {getdate(day): kind for day, kind in (holidays or {}).items()}
	cumulate = rules.get("supplements_cumulate") is True
	minutes = defaultdict(int)
	for start, end in intervals:
		moment = get_datetime(start).replace(second=0, microsecond=0)
		end = get_datetime(end)
		while moment < end:
			matching = [index for index, row in enumerate(table) if _matches(row, moment, holidays)]
			for index in _applying(table, matching, cumulate):
				minutes[(moment.date(), index)] += 1
			moment += datetime.timedelta(minutes=1)
	lines = []
	for (day, index), count in sorted(minutes.items()):
		row = table[index]
		lines.append(
			{
				"date": day,
				"label": row.get("label"),
				"article": row.get("article"),
				"hours": flt(count / 60, 4),
				"percent": flt(row.get("percent")) or None,
				"amount_per_hour": flt(row.get("amount_per_hour")) or None,
			}
		)
	return lines


# ------------------------------------------------------------------------------------------ the database


def worked_intervals(employee: str, first, last) -> list:
	"""The intervals worked by an employee from `first` to `last` (days): check-ins, else the attendance's times."""
	import frappe

	first, last = getdate(first), getdate(last)
	logs = frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": employee,
			"time": ["between", [f"{first} 00:00:00", f"{last + datetime.timedelta(days=1)} 12:00:00"]],
		},
		fields=["time", "log_type"],
		order_by="time asc",
	)
	intervals, opened = [], None
	for log in logs:
		if log.log_type == "IN":
			opened = get_datetime(log.time)
		elif log.log_type == "OUT" and opened:
			if first <= opened.date() <= last:
				intervals.append((opened, get_datetime(log.time)))
			opened = None
	worked_days = {start.date() for start, _ in intervals}
	rows = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"docstatus": 1,
			"attendance_date": ["between", [first, last]],
			"in_time": ["is", "set"],
			"out_time": ["is", "set"],
		},
		fields=["attendance_date", "in_time", "out_time"],
	)
	for row in rows:
		if getdate(row.attendance_date) not in worked_days:
			intervals.append((get_datetime(row.in_time), get_datetime(row.out_time)))
	# a day the HR manager corrected is read from the correction, never from the clock (correction.py)
	from hrms.hr.working_time.correction import as_datetimes, corrected_days

	corrected = corrected_days(employee, first, last)
	if corrected:
		intervals = [pair for pair in intervals if pair[0].date() not in corrected]
		for day, correction in corrected.items():
			intervals.extend(as_datetimes(day, correction["intervals"]))
	return sorted(intervals)


def supplements_of(employee: str, first, last) -> list | None:
	"""The supplement lines of an employee from `first` to `last`; None without an agreement."""
	from frappe.utils import cint

	from hrms.hr.utils import get_holidays_for_employee
	from hrms.hr.working_time.agreement import rules_for

	rules = rules_for(employee)
	if rules is None:
		return None
	holidays = {
		getdate(holiday.holiday_date): "weekly_off" if cint(holiday.weekly_off) else "holiday"
		for holiday in get_holidays_for_employee(employee, first, last, raise_exception=False) or []
	}
	return supplement_lines(rules, worked_intervals(employee, first, last), holidays)
