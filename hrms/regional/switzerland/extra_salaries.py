# //// Neoffice — added file (no upstream equivalent): the 13th, 14th and 15th salaries of the Swiss
# //// payroll — accrued every month from the base salary paid, paid on their schedule.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Extra salaries: the 13th, the 14th and the 15th.

A contractual extra salary is salary (CO 322): earned month by month, due pro rata at the entry
and at the exit, whatever its schedule. Each one is set on the company's social insurance
configuration with its share of a monthly salary (100 % for a full 13th) and its schedule: with
every salary (a twelfth), once a year (December unless another month is chosen), twice (June and
December) or four times (March, June, September and December).

The amount paid is the base salary paid since the previous payment, divided by twelve —
Swissdec's cumulated 13th base (guidelines 6.0): a raise, an unpaid leave or an entry during the
period count as they were paid. A month of that period without a slip in this payroll while the
employee was employed — a company that started its payroll here during the year — counts the
current base salary, prorated to the days employed.

Source tax: periodic, extrapolated with the salary in an entry or exit month, whatever the
schedule (Swissdec guidelines 6.0 §10.6.1.2; annex 1 cases M17, M18, M20, M21, M22).

Each slip keeps what every extra salary accrued and paid on it (Salary Slip.ch_extra_salaries):
the salary booking provisions the accrual and releases it when paid (accounting.py).
"""

import calendar
import datetime
import json

import frappe
from frappe.utils import add_months, cint, flt, get_last_day, getdate

from hrms.regional.switzerland.constants import BASE_SALARY_WAGE_TYPE_CODES
from hrms.regional.switzerland.rounding import round_to_5_centimes

# extra salary -> (wage type code, component name of the Swiss setup)
SALARIES = {
	"13th": ("1200", "13th Month Salary"),
	"14th": ("1205", "14th Month Salary"),
	"15th": ("1206", "15th Month Salary"),
}
MONTHLY, ANNUAL, HALF_YEARLY, QUARTERLY = "Monthly", "Annual", "Half-yearly", "Quarterly"
SCHEDULE_MONTHS = {HALF_YEARLY: (6, 12), QUARTERLY: (3, 6, 9, 12)}


def extra_salaries(config):
	"""The company's extra salaries: [frappe._dict(extra_salary, percent, schedule, payment_month)].

	The table of its social insurance configuration; while it is empty, the legacy single setting
	(thirteenth_month_mode) as one 13th at 100 %.
	"""
	if not config:
		return []
	rows = config.get("extra_salaries")
	if rows is None and config.get("name"):
		rows = frappe.get_all(
			"Swiss Extra Salary",
			filters={"parent": config.get("name"), "parenttype": "Swiss Social Insurance Config"},
			fields=["extra_salary", "percent", "schedule", "payment_month"],
			order_by="idx",
		)
	rows = [frappe._dict(row) for row in rows or [] if frappe._dict(row).extra_salary in SALARIES]
	if rows:
		return rows
	mode = config.get("thirteenth_month_mode") or "Disabled"
	if mode in (ANNUAL, MONTHLY):
		return [frappe._dict(extra_salary="13th", percent=100, schedule=mode, payment_month=12)]
	return []


def set_thirteenth(doc, mode):
	"""Set a configuration's 13th from the legacy single choice (Disabled, Annual, Monthly): its
	row of the extra salaries table follows, the 14th and 15th stay as they are."""
	doc.thirteenth_month_mode = mode
	rows = [row for row in doc.get("extra_salaries") or [] if row.extra_salary != "13th"]
	if mode in (ANNUAL, MONTHLY):
		current = next((row for row in doc.get("extra_salaries") or [] if row.extra_salary == "13th"), None)
		rows.insert(
			0,
			{
				"extra_salary": "13th",
				"percent": current.percent if current else 100,
				"schedule": mode,
				"payment_month": (current.payment_month if current else 12) or 12,
			},
		)
	doc.set("extra_salaries", [dict(row) if not isinstance(row, dict) else row for row in rows])


def salaries_per_year(config):
	"""The months of salary in a year: 12 and each extra salary's share (13 with a full 13th).

	The LPP annual salary is the monthly base times this (Swissdec §8.6.6); the pension fund's
	regulations may say otherwise.
	"""
	return 12 + sum(flt(row.percent) / 100 for row in extra_salaries(config))


def payment_months(row):
	if row.schedule == MONTHLY:
		return tuple(range(1, 13))
	if row.schedule == ANNUAL:
		return (min(max(cint(row.payment_month) or 12, 1), 12),)
	return SCHEDULE_MONTHS.get(row.schedule, (12,))


def accrual_start(row, period_start):
	"""First day of the accrual period of the slip: the month after the previous payment."""
	start = getdate(period_start)
	months = sorted(payment_months(row))
	before = [month for month in months if month < start.month]
	if before:
		return datetime.date(start.year, before[-1] + 1, 1)
	if months[-1] == 12:
		return datetime.date(start.year, 1, 1)
	return datetime.date(start.year - 1, months[-1] + 1, 1)


def _is_base(component, abbr=None, code=None):
	code = (
		code
		if code is not None
		else frappe.get_cached_value("Salary Component", component, "ch_wage_type_code")
	)
	if code:
		return cint(code) in BASE_SALARY_WAGE_TYPE_CODES
	return component == "Basic" or abbr == "B"


def base_paid(doc, full=False):
	"""The base salary of the slip: paid (after the days paid), or ``full`` for the whole month."""
	return sum(
		flt(row.default_amount if full else row.amount)
		for row in doc.get("earnings") or []
		if _is_base(row.salary_component, row.get("abbr"))
	)


def _base_paid_by_month(employee, company, since, before, exclude=None):
	"""{(year, month): base salary paid} by the employee's submitted slips in [since, before)."""
	rows = frappe.db.sql(
		"""SELECT ss.start_date, sd.amount, sd.salary_component, sd.abbr, sc.ch_wage_type_code
		FROM `tabSalary Slip` ss
		JOIN `tabSalary Detail` sd
			ON sd.parent = ss.name AND sd.parenttype = 'Salary Slip' AND sd.parentfield = 'earnings'
		JOIN `tabSalary Component` sc ON sc.name = sd.salary_component
		WHERE ss.employee = %(employee)s AND ss.company = %(company)s AND ss.docstatus = 1
			AND ss.start_date >= %(since)s AND ss.start_date < %(before)s AND ss.name != %(exclude)s""",
		{
			"employee": employee,
			"company": company,
			"since": since,
			"before": before,
			"exclude": exclude or "",
		},
		as_dict=True,
	)
	paid = {}
	for row in rows:
		if _is_base(row.salary_component, row.abbr, row.ch_wage_type_code or ""):
			day = getdate(row.start_date)
			paid[(day.year, day.month)] = paid.get((day.year, day.month), 0) + flt(row.amount)
	return paid


def cumulated_base(doc, since, employee):
	"""The base salary from ``since`` up to and including this slip's month.

	A month with a submitted slip counts what it paid; a month employed without a slip here counts
	the current full base, prorated to the calendar days employed; this month counts this slip.
	"""
	start, since = getdate(doc.start_date), getdate(since)
	paid = _base_paid_by_month(doc.employee, doc.company, since, start, exclude=doc.get("name"))
	full_base = base_paid(doc, full=True)
	joining = getdate(employee.get("date_of_joining")) if employee.get("date_of_joining") else None
	total = base_paid(doc)
	month = datetime.date(since.year, since.month, 1)
	while month < datetime.date(start.year, start.month, 1):
		if (month.year, month.month) in paid:
			total += paid[(month.year, month.month)]
		else:
			last = getdate(get_last_day(month))
			first = max(month, joining) if joining else month
			if first <= last:
				days_in_month = calendar.monthrange(month.year, month.month)[1]
				total += full_base * ((last - first).days + 1) / days_in_month
		month = getdate(add_months(month, 1))
	return total


def component_of(extra_salary):
	"""The salary component of an extra salary: by its wage type, else the Swiss setup's name."""
	code, name = SALARIES[extra_salary]
	component = frappe.db.get_value("Salary Component", {"ch_wage_type_code": code}, "name")
	return component or (name if frappe.db.exists("Salary Component", name) else None)


def compute(doc, config, employee):
	"""What each extra salary accrues and pays on the slip.

	[{extra_salary, schedule, component, accrued, paid}]: ``accrued`` is this month's share of the
	base paid, ``paid`` the amount due on this slip — every month for a monthly schedule, the
	cumulated base since the previous payment in a payment month or the exit month, else 0.
	"""
	rows = extra_salaries(config)
	if not rows:
		return []
	start, end = getdate(doc.start_date), getdate(doc.end_date)
	relieving = employee.get("relieving_date")
	exiting = bool(relieving) and start <= getdate(relieving) <= end
	this_month = base_paid(doc)
	results = []
	for row in rows:
		share = flt(row.percent) / 100
		if share <= 0:
			continue
		accrued = this_month * share / 12
		if row.schedule == MONTHLY:
			due = accrued
		elif end.month in payment_months(row) or exiting:
			due = cumulated_base(doc, accrual_start(row, start), employee) * share / 12
		else:
			due = 0
		results.append(
			{
				"extra_salary": row.extra_salary,
				"schedule": row.schedule,
				"component": component_of(row.extra_salary),
				"accrued": flt(accrued, 2),
				"paid": round_to_5_centimes(due) if due else 0,
			}
		)
	return results


def slip_extra_salaries(doc):
	"""The extra salaries recorded on a slip (list of dicts), empty when none."""
	value = doc.get("ch_extra_salaries") if hasattr(doc, "get") else None
	if not value:
		return []
	return json.loads(value) if isinstance(value, str) else value
