# //// Neoffice — added file (no upstream equivalent): the vacation of a person counted in hours, when their
# //// labour agreement says so (lot T, neoffice-maintenance#2623).
"""The vacation counted in hours (`vacation_unit` = Hours), for a person who works part time or uneven days.

The year of vacation in hours is its weeks (the yearly days divided by the five working days of a full week) times
the person's hours due a week (the agreement's, times their activity rate when it says part time follows it):
22.5 days at 43 h and 80 % make 4.5 weeks of 34.4 h, 154.8 h. A day of vacation taken costs the hours due that
day, half of them on a half day: a short day costs less than a long one, which a count in days cannot say.

Leave in hrms is counted in days; this is the reading in hours beside it, never a second ledger: the days stay
the leave's. `vacation_in_hours` is pure; `vacation_hours_of` reads the yearly days (`hrms.regional.switzerland`
vacation: the allocation, the agreement's table, the company's setting), the hours due and the vacation taken.
"""

import datetime

from frappe.utils import flt, getdate, nowdate

from hrms.hr.working_time import rules as catalogue

FULL_WEEK_DAYS = 5


def vacation_in_hours(rules, days_entitled, weekly_due, taken_hours) -> dict | None:
	"""The year's vacation in hours: entitled, taken, left; None when the agreement does not count it in hours."""
	if rules.get("vacation_unit") != catalogue.HOURS or days_entitled is None or weekly_due is None:
		return None
	entitled = flt(days_entitled) / FULL_WEEK_DAYS * flt(weekly_due)
	taken = sum(flt(hours) for hours in taken_hours)
	return {
		"unit": catalogue.HOURS,
		"days_entitled": flt(days_entitled, 4),
		"weekly_due": flt(weekly_due, 4),
		"entitled": flt(entitled, 4),
		"taken": flt(taken, 4),
		"left": flt(entitled - taken, 4),
	}


def vacation_hours_of(employee: str, on_date=None) -> dict | None:
	"""The vacation in hours of an employee for the calendar year of `on_date`, taken until that day."""
	import frappe

	from hrms.hr.working_time.agreement import rules_for
	from hrms.hr.working_time.week import compute_week, employee_facts, weekly_hours_due
	from hrms.regional.switzerland import vacation

	rules = rules_for(employee)
	if rules is None or rules.get("vacation_unit") != catalogue.HOURS:
		return None
	on_date = getdate(on_date or nowdate())
	leave_type = vacation.vacation_leave_type()
	monday = on_date - datetime.timedelta(days=on_date.weekday())
	weekly_due = weekly_hours_due(rules, employee_facts(employee, monday), monday)
	days_entitled = vacation.yearly_entitlement(employee, leave_type, on_date)
	taken_days = frappe.get_all(
		"Attendance",
		filters={
			"employee": employee,
			"docstatus": 1,
			"leave_type": leave_type,
			"status": ["in", ["On Leave", "Half Day"]],
			"attendance_date": ["between", [datetime.date(on_date.year, 1, 1), on_date]],
		},
		fields=["attendance_date", "status"],
	)
	weeks, taken = {}, []
	for row in taken_days:
		day = getdate(row.attendance_date)
		start = day - datetime.timedelta(days=day.weekday())
		if start not in weeks:
			week = compute_week(rules, employee_facts(employee, start), start)
			weeks[start] = {getdate(entry["date"]): entry["due"] for entry in week.days} if week else {}
		due = weeks[start].get(day, 0.0)
		taken.append(due / 2 if row.status == "Half Day" else due)
	return vacation_in_hours(rules, days_entitled, weekly_due, taken)
