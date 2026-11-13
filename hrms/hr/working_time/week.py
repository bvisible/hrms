# //// Neoffice — added file (no upstream equivalent): the hours due, done and over of one week of an employee,
# //// read from the confirmed rules of their labour agreement (lot T, neoffice-maintenance#2623).
"""The ledger of one week: what was due, what was done, what is over.

The hours due come from the agreement's target (a number of hours a week, the hours of the company's status, a
calendar of the year, or the contract's own hours), times the activity rate when the agreement says part time
follows it, spread evenly over the person's working days (the days of their holiday list that are not a weekly
day off). A public holiday on a working day and a paid absence are credited the hours due that day. The hours
done are the attendance's working hours (the clock, never typed here).

The difference less the tolerance is the hours over; above the legal maximum of the week the excess is also
counted apart, for the yearly legal counter. Nothing is blocked: a figure is a figure, a warning a warning.

`compute_week` is pure (every fact is passed in) so that each rule can be tested on its own; `week_of` reads the
facts of an employee from the database and returns None when no agreement is tied to them, or when the confirmed
rules do not say how many hours are due.
"""

import datetime
from dataclasses import dataclass, field

from frappe.utils import add_days, cint, flt, getdate

from hrms.hr.working_time import rules as catalogue

WEEKS_A_YEAR = 365 / 7


@dataclass
class Facts:
	"""What the engine needs to know of a person for a week, besides their agreement."""

	activity_rate: float = 100.0
	contract_weekly_hours: float = 0.0
	# dates of the week: "weekly_off" or "holiday" (a public holiday that is not a weekly day off)
	holidays: dict = field(default_factory=dict)
	# date -> {"status": Attendance status, "working_hours": float, "paid_leave": bool,
	#          "leave": None, "paid", "unpaid" or "compensatory"}
	attendance: dict = field(default_factory=dict)


@dataclass
class Week:
	monday: datetime.date
	days: list
	weekly_due: float
	due: float
	done: float
	credited: float
	difference: float
	tolerance: float
	over: float
	short: float
	legal_excess: float
	needs_approval: bool
	indicative: bool
	warnings: list


def weekly_hours_due(rules, facts: Facts, monday) -> float | None:
	"""The hours due for the whole week, before the days off: None when the confirmed rules do not settle it."""
	target = rules.get("target")
	hours = None
	if target == catalogue.WEEKLY_HOURS:
		hours = rules.get("weekly_hours")
	elif target == catalogue.BY_COMPANY_STATUS:
		status = rules.get("company_status")
		rows = rules.get("company_status_hours") or []
		hours = next((flt(row["hours"]) for row in rows if row["status"] == status), None)
	elif target == catalogue.ANNUAL_CALENDAR:
		hours = _calendar_hours(rules, monday)
	elif target == catalogue.CONTRACT_HOURS:
		return flt(facts.contract_weekly_hours) or None
	if hours is None:
		return None
	if rules.get("pro_rata", True) is not False:
		hours = flt(hours) * flt(facts.activity_rate) / 100
	return flt(hours)


def _calendar_hours(rules, monday):
	"""The week's hours of the company's calendar; without a calendar, the hours of the year spread evenly."""
	monday = getdate(monday)
	for row in rules.get("annual_calendar") or []:
		if getdate(row["from"]) <= monday <= getdate(row["to"]):
			return flt(row["hours"])
	annual = rules.get("annual_hours")
	return flt(annual) / WEEKS_A_YEAR if annual else None


def compute_week(rules, facts: Facts, monday, indicative: bool = False) -> Week | None:
	"""The ledger of the week that starts on `monday` (any day of it), or None when the hours due are not settled."""
	monday = getdate(monday)
	monday = monday - datetime.timedelta(days=monday.weekday())
	weekly = weekly_hours_due(rules, facts, monday)
	if weekly is None:
		return None
	dates = [monday + datetime.timedelta(days=offset) for offset in range(7)]
	working = [day for day in dates if facts.holidays.get(day) != "weekly_off"]
	share = weekly / len(working) if working else 0.0
	days, warnings = [], []
	for day in dates:
		kind = facts.holidays.get(day)
		due = 0.0 if kind == "weekly_off" else share
		seen = facts.attendance.get(day) or {}
		done = (
			flt(seen.get("working_hours"))
			if seen.get("status") in ("Present", "Half Day", "Work From Home")
			else 0.0
		)
		credited = 0.0
		if kind == "holiday":
			credited = due
		elif seen.get("status") == "On Leave" and seen.get("paid_leave"):
			credited = due
		elif seen.get("status") == "Half Day" and seen.get("paid_leave"):
			credited = due / 2
		days.append(
			{
				"date": day,
				"kind": kind or "work",
				"due": flt(due, 4),
				"done": flt(done, 4),
				"credited": flt(credited, 4),
				# what the days of rest are read from (rest.py)
				"status": seen.get("status"),
				"leave": seen.get("leave") or ("paid" if seen.get("paid_leave") else None),
			}
		)
	due = sum(day["due"] for day in days)
	done = sum(day["done"] for day in days)
	credited = sum(day["credited"] for day in days)
	difference = done + credited - due
	tolerance = flt(rules.get("tolerance_hours") or 0)
	if tolerance and rules.get("pro_rata", True) is not False:
		tolerance = tolerance * flt(facts.activity_rate) / 100
	absorbed = min(max(difference, 0), tolerance) if rules.get("tolerance_fate") == catalogue.LOST else 0.0
	over = max(difference - absorbed, 0.0)
	short = min(difference, 0.0)
	legal_max = rules.get("legal_weekly_maximum")
	legal_excess = max(done - flt(legal_max), 0.0) if legal_max else 0.0
	if legal_excess:
		warnings.append("legal_weekly_maximum")
	return Week(
		monday=monday,
		days=days,
		weekly_due=flt(weekly, 4),
		due=flt(due, 4),
		done=flt(done, 4),
		credited=flt(credited, 4),
		difference=flt(difference, 4),
		tolerance=flt(absorbed, 4),
		over=flt(over, 4),
		short=flt(short, 4),
		legal_excess=flt(legal_excess, 4),
		needs_approval=bool(over and rules.get("employer_order_required")),
		indicative=indicative,
		warnings=warnings,
	)


# ------------------------------------------------------------------------------------------ the database


def employee_facts(employee: str, monday) -> Facts:
	"""The facts of a week of an employee: activity rate, contract hours, days off and holidays, attendance."""
	import frappe

	from hrms.hr.utils import get_holidays_for_employee
	from hrms.hr.working_time.agreement import CONTRACT_HOURS_FIELD

	monday = getdate(monday)
	sunday = add_days(monday, 6)
	meta = frappe.get_meta("Employee")
	fields = [name for name in ("ch_work_percentage", CONTRACT_HOURS_FIELD) if meta.has_field(name)]
	person = frappe.db.get_value("Employee", employee, fields, as_dict=True) if fields else {}
	facts = Facts(
		activity_rate=flt((person or {}).get("ch_work_percentage")) or 100.0,
		contract_weekly_hours=flt((person or {}).get(CONTRACT_HOURS_FIELD)),
	)
	for holiday in get_holidays_for_employee(employee, monday, sunday, raise_exception=False) or []:
		facts.holidays[getdate(holiday.holiday_date)] = (
			"weekly_off" if cint(holiday.weekly_off) else "holiday"
		)
	rows = frappe.get_all(
		"Attendance",
		filters={"employee": employee, "docstatus": 1, "attendance_date": ["between", [monday, sunday]]},
		fields=["attendance_date", "status", "working_hours", "leave_type"],
	)
	unpaid = set(frappe.get_all("Leave Type", filters={"is_lwp": 1}, pluck="name"))
	compensatory = set(frappe.get_all("Leave Type", filters={"is_compensatory": 1}, pluck="name"))
	for row in rows:
		leave = None
		if row.leave_type:
			leave = (
				"compensatory"
				if row.leave_type in compensatory
				else ("unpaid" if row.leave_type in unpaid else "paid")
			)
		facts.attendance[getdate(row.attendance_date)] = {
			"status": row.status,
			"working_hours": flt(row.working_hours),
			"paid_leave": leave in ("paid", "compensatory"),
			"leave": leave,
		}
	return facts


def week_of(employee: str, day, confirmed_only: bool = True) -> Week | None:
	"""The ledger of an employee's week, from their agreement: None without an agreement or a settled target.

	`confirmed_only=False` gives the indicative reading (the lines to confirm let in), marked as such."""
	from hrms.hr.working_time.agreement import rules_for

	rules = rules_for(employee, confirmed_only=confirmed_only)
	if rules is None:
		return None
	return compute_week(rules, employee_facts(employee, day), day, indicative=rules.indicative)
