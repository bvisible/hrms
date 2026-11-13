# //// Neoffice — added file (no upstream equivalent): the weeks the engine keeps, the employer's approval of the
# //// hours over, and the balance read from them (lot T, neoffice-maintenance#2623).
"""The weeks kept, and the balance drawn from them.

`record_week` writes an employee's week from the confirmed rules (an indicative week is never written: it feeds
nothing). Its figures follow the clock: when they change after an approval, the approval is withdrawn, since the
employer approved other hours. `approve_week` is the employer's approval, a person and a moment, for all or part
of the hours over; only someone who may write the week approves. `balance_of` gives the balance of an employee on a
day, from the weeks kept: the hours over that wait for an approval are not in it. A week kept also carries its
days of rest (`rest.py`), and `rest_of` gives the rest days owed and the Sundays to compensate on a day.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_last_day, getdate, now_datetime, nowdate

from hrms.hr.working_time.agreement import CONFIRMED, EMPLOYEE_FIELD, EXTENSION_FIELD, ROW, rules_for
from hrms.hr.working_time.balance import WeekLine, compute_balance, overtime_supplement
from hrms.hr.working_time.rest import rest_account, rest_of_week
from hrms.hr.working_time.week import week_of

WEEK_DOCTYPE = "Working Time Week"
FIGURES = ("due", "done", "credited", "difference", "tolerance", "over", "short", "legal_excess")


def _monday(day):
	day = getdate(day)
	return add_days(day, -day.weekday())


def record_week(employee: str, day) -> str | None:
	"""Write (or rewrite) the week of `day` for an employee; None when the confirmed rules settle no week."""
	week = week_of(employee, day)
	monday = _monday(day)
	name = frappe.db.get_value(WEEK_DOCTYPE, {"employee": employee, "monday": monday})
	if week is None:
		return None
	doc = frappe.get_doc(WEEK_DOCTYPE, name) if name else frappe.new_doc(WEEK_DOCTYPE)
	changed = any(abs(flt(doc.get(field)) - flt(getattr(week, field))) > 0.004 for field in FIGURES)
	doc.employee = employee
	doc.monday = monday
	doc.agreement = frappe.db.get_value("Employee", employee, EMPLOYEE_FIELD)
	for field in FIGURES:
		doc.set(field, flt(getattr(week, field), 4))
	doc.needs_approval = 1 if week.needs_approval else 0
	if changed and doc.approved_by:
		doc.approved_by, doc.approved_on, doc.approved_hours = None, None, 0
	doc.days = json.dumps(week.days, default=str)
	rules = rules_for(employee)
	rest = rest_of_week(rules if rules is not None else {}, week.days)
	doc.days_off = rest.days_off
	doc.days_off_missing = rest.missing
	doc.sundays_holidays_worked = flt(sum(day["days"] for day in rest.sundays_holidays), 4)
	doc.compensatory_days = rest.compensatory
	doc.computed_on = now_datetime()
	doc.flags.ignore_permissions = True
	doc.save() if name else doc.insert()
	return doc.name


@frappe.whitelist()
def approve_week(week: str, hours: float | None = None) -> dict:
	"""The employer approves the hours over of a week (all of them, or `hours`): the person and the moment are kept."""
	doc = frappe.get_doc(WEEK_DOCTYPE, week)
	doc.check_permission("write")
	if not doc.needs_approval:
		frappe.throw(_("This week has no hours over waiting for the employer."))
	wanted = flt(doc.over) if hours in (None, "") else flt(hours)
	if wanted < 0 or wanted > flt(doc.over) + 0.004:
		frappe.throw(_("Between 0 and {0} hours can be approved for this week.").format(flt(doc.over, 2)))
	doc.approved_hours = flt(wanted, 4)
	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	doc.save()
	return {"week": doc.name, "approved_hours": doc.approved_hours, "by": doc.approved_by}


def counted_over(row) -> float:
	"""The hours over a week brings to the balance: the approved ones when the agreement wants an approval."""
	if row.get("needs_approval"):
		return flt(row.get("approved_hours")) if row.get("approved_by") else 0.0
	return flt(row.get("over"))


def balance_of(employee: str, on_date=None):
	"""The balance of an employee on a day, from the weeks kept; None without an agreement or a way of keeping it."""
	rules = rules_for(employee)
	if rules is None:
		return None
	on_date = getdate(on_date or nowdate())
	rows = frappe.get_all(
		WEEK_DOCTYPE,
		filters={"employee": employee, "monday": ["<=", on_date]},
		fields=["monday", "over", "short", "legal_excess", "needs_approval", "approved_hours", "approved_by"],
		order_by="monday asc",
	)
	weeks = [
		WeekLine(
			monday=getdate(row.monday),
			over=counted_over(row),
			short=abs(flt(row.short)),
			legal_excess=flt(row.legal_excess),
		)
		for row in rows
	]
	extended = bool(frappe.db.get_value("Employee", employee, EXTENSION_FIELD))
	supplement = overtime_supplement(
		rules,
		recorded=_recorded([week.monday for week in weeks], on_date),
		communicated=_communicated(employee, weeks[0].monday if weeks else None, on_date),
	)
	from hrms.hr.working_time.closing import decisions_of

	return compute_balance(
		rules,
		weeks,
		on_date,
		extended_in_writing=extended,
		supplement=supplement,
		decisions=decisions_of(employee),
	)


def _recorded(mondays, on_date) -> bool:
	"""Whether every week was kept, from the first one to the last week ended by `on_date`."""
	if not mondays:
		return False
	kept = set(mondays)
	last = _monday(add_days(getdate(on_date), -6))
	monday = min(kept)
	while monday <= last:
		if monday not in kept:
			return False
		monday = add_days(monday, 7)
	return True


def _communicated(employee: str, first_monday, on_date) -> bool:
	"""Whether a statement was given for every month ended by `on_date`, from the month of the first week kept."""
	from hrms.hr.working_time.statement import STATEMENT_DOCTYPE

	if not first_monday:
		return False
	given = {
		getdate(month).replace(day=1)
		for month in frappe.get_all(
			STATEMENT_DOCTYPE,
			filters={"employee": employee, "copy_given_on": ["is", "set"]},
			pluck="month",
		)
	}
	month = getdate(first_monday).replace(day=1)
	current = getdate(on_date).replace(day=1)
	while month < current:
		if month not in given:
			return False
		month = getdate(add_days(get_last_day(month), 1))
	return True


def record_recent_weeks():
	"""Scheduler (daily): the last week and this one, and the closings reached, for every active employee tied to
	an agreement. It runs on every site: one query, and a site where no line of an agreement is confirmed leaves at
	once, reading and writing nothing."""
	if not frappe.db.exists(ROW, {"state": CONFIRMED}):
		return
	if not frappe.get_meta("Employee").has_field(EMPLOYEE_FIELD):
		return
	today = getdate(nowdate())
	employees = frappe.get_all(
		"Employee", filters={"status": "Active", EMPLOYEE_FIELD: ["is", "set"]}, pluck="name"
	)
	from hrms.hr.working_time.closing import record_closings

	for employee in employees:
		for day in (add_days(today, -7), today):
			try:
				record_week(employee, day)
			except Exception:
				frappe.log_error("Working time: a week could not be recorded", frappe.get_traceback())
		try:
			record_closings(employee, today)
		except Exception:
			frappe.log_error("Working time: a closing could not be recorded", frappe.get_traceback())


def rest_of(employee: str, on_date=None):
	"""The days of rest of an employee on a day, from the weeks kept; None without an agreement."""
	rules = rules_for(employee)
	if rules is None:
		return None
	on_date = getdate(on_date or nowdate())
	rows = frappe.get_all(
		WEEK_DOCTYPE,
		filters={"employee": employee, "monday": ["<=", on_date]},
		fields=["days"],
		order_by="monday asc",
	)
	weeks = []
	for row in rows:
		days = json.loads(row.days or "[]")
		if days:
			weeks.append((rest_of_week(rules, days), days))
	person = frappe.db.get_value("Employee", employee, ["date_of_joining", "relieving_date"], as_dict=True)
	return rest_account(
		rules, weeks, on_date, employed_from=person.date_of_joining, employed_to=person.relieving_date
	)
