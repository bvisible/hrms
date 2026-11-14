# //// Neoffice — added file (no upstream equivalent): the check of the minimum wage, which warns and never changes a
# //// pay (lot T, neoffice-maintenance#2623).
"""The check of the minimum wage: a month's pay against the minimum of the person's agreement and of their canton.

Every amount is a line of the agreement the client confirmed, with its source: the table of minimum wages (a row by
category, years of experience, zone and validity), whether the minimum follows the activity rate, the cantonal
minimum (hourly, for whoever works in that canton), the period of the check and the reduction an agreement allows
when a month's turnover stays under a threshold. A line that is not confirmed checks nothing, and the check says so.

What counts toward the minimum is the client's to say: the agreement says it in words (`minimum_wage_counts`), the
client ticks the salary components that hold it (`counts_toward_minimum_wage`); a month's pay is the sum of those
components on the person's pay slips of the month. Without a ticked component, nothing is compared.

The check warns and never blocks: a pay slip under the minimum is saved as it is, with a message. A month counts at
the years of experience reached on its first day. The minimum due is the higher of the agreement's and the canton's.
"""

import datetime

import frappe
from frappe import _
from frappe.utils import add_days, flt, formatdate, get_first_day, get_last_day, getdate

from hrms.hr.working_time import rules as catalogue
from hrms.hr.working_time.agreement import DEDUCED, TO_CONFIRM, rules_for

CATEGORY_FIELD = "minimum_wage_category"
EXPERIENCE_FIELD = "experience_since"
ZONE_FIELD = "minimum_wage_zone"
CANTON_FIELD = "work_canton"
REDUCTION_FIELD = "minimum_wage_reduction_agreed"
COUNTS_FIELD = "counts_toward_minimum_wage"
EMPLOYEE_FIELDS = (CATEGORY_FIELD, EXPERIENCE_FIELD, ZONE_FIELD, CANTON_FIELD, REDUCTION_FIELD)
# states of a month's check
UNDER, REACHED, NO_PAY, NOT_CHECKED = "under", "reached", "no_pay", "not_checked"
# an app that knows a person's turnover of a month answers through this hook: (employee, first, last) -> float | None
TURNOVER_HOOK = "working_time_turnover_providers"


def _same(left, right) -> bool:
	return (left or "").strip().casefold() == (right or "").strip().casefold()


def completed_years(since, on_day) -> int:
	"""Completed years from `since` to `on_day`."""
	since, on_day = getdate(since), getdate(on_day)
	years = on_day.year - since.year
	if (on_day.month, on_day.day) < (since.month, since.day):
		years -= 1
	return max(years, 0)


def _person(employee: str) -> frappe._dict:
	meta = frappe.get_meta("Employee")
	fields = ["name", "employee_name", "company"] + [
		name for name in (*EMPLOYEE_FIELDS, "ch_work_percentage") if meta.has_field(name)
	]
	return frappe.db.get_value("Employee", employee, fields, as_dict=True) or frappe._dict()


def _valid_on(row, day) -> bool:
	return getdate(row["valid_from"]) <= day <= getdate(row["valid_to"])


def _agreement_row(table, person, first):
	"""The row of the table for the person on the month, or (None, why)."""
	category = person.get(CATEGORY_FIELD)
	if not category:
		return None, _("The person has no category for the minimum wage.")
	rows = [row for row in table if _same(row.get("category"), category)]
	if not rows:
		return None, _("The table of minimum wages has no category « {0} ».").format(category)
	rows = [row for row in rows if not row.get("zone") or _same(row.get("zone"), person.get(ZONE_FIELD))]
	if not rows:
		return None, _("The person has no zone of the table of minimum wages.")
	valid = [row for row in rows if _valid_on(row, first)]
	if not valid:
		last = max(getdate(row["valid_to"]) for row in rows)
		if last < first:
			return None, _("The table of minimum wages ends on {0}: bring it up to date.").format(
				frappe.format(last, {"fieldtype": "Date"})
			)
		return None, _("The table of minimum wages has no row valid on {0}.").format(
			frappe.format(first, {"fieldtype": "Date"})
		)
	if any(row.get("experience_from") or row.get("experience_to") is not None for row in valid):
		if not person.get(EXPERIENCE_FIELD):
			return None, _("The person's professional experience has no start date.")
		years = completed_years(person.get(EXPERIENCE_FIELD), first)
		valid = [
			row
			for row in valid
			if flt(row.get("experience_from")) <= years
			and (row.get("experience_to") is None or years < flt(row["experience_to"]))
		]
		if not valid:
			return None, _("The table of minimum wages has no row for {0} years of experience.").format(years)
	return valid[0], None


def _month_hours(employee: str, first, last) -> float | None:
	"""The hours due of the month, from the weeks the engine kept; None when no week of the month is kept."""
	import json

	from hrms.hr.working_time.store import WEEK_DOCTYPE

	hours, seen = 0.0, False
	for days in frappe.get_all(
		WEEK_DOCTYPE,
		filters={"employee": employee, "monday": ["between", [add_days(first, -6), last]]},
		pluck="days",
	):
		for day in json.loads(days or "[]"):
			if first <= getdate(day.get("date")) <= last:
				hours += flt(day.get("due"))
				seen = True
	return hours if seen else None


def _turnover(employee: str, first, last):
	for path in frappe.get_hooks(TURNOVER_HOOK) or []:
		value = frappe.get_attr(path)(employee, first, last)
		if value is not None:
			return flt(value)
	return None


def minimum_of(employee: str, month) -> dict | None:
	"""The minimum due to a person for a month, with what it is made of and what could not be read.

	None when no agreement is tied to the person. `amount` is None when nothing confirmed gives a minimum."""
	rules = rules_for(employee)
	if rules is None:
		return None
	first = get_first_day(getdate(month))
	last = get_last_day(first)
	person = _person(employee)
	rate = flt(person.get("ch_work_percentage")) or 100.0
	out = {
		"month": first,
		"amount": None,
		"agreement": None,
		"cantonal": None,
		"reduction": None,
		"notes": [],
	}

	table = rules.get("minimum_wages")
	if table:
		row, why = _agreement_row(table, person, first)
		if why:
			out["notes"].append(why)
		else:
			monthly = row.get("monthly")
			if monthly is None and row.get("hourly") is not None and rules.has("hourly_divisor"):
				monthly = flt(row["hourly"]) * flt(rules.get("hourly_divisor"))
			if monthly is None:
				out["notes"].append(
					_("The row of the table gives no monthly amount, nor a divisor to make one.")
				)
			elif rate < 100 and not rules.has("minimum_wage_pro_rata"):
				out["notes"].append(
					_(
						"Whether the minimum follows the activity rate is not confirmed: a part time is not checked."
					)
				)
			else:
				share = rate / 100 if rules.get("minimum_wage_pro_rata") else 1
				out["agreement"] = {
					"amount": flt(flt(monthly) * share, 2),
					"category": row.get("category"),
					"article": row.get("article") or rules.source("minimum_wages").get("article"),
					"until": row.get("valid_to"),
				}
	elif rules.state("minimum_wages") in (TO_CONFIRM, DEDUCED):
		out["notes"].append(_("The table of minimum wages is not confirmed: it checks nothing."))

	cantonal = rules.get("cantonal_minimum_wages")
	if cantonal:
		canton = person.get(CANTON_FIELD)
		rows = [row for row in cantonal if _same(row["canton"], canton) and _valid_on(row, first)]
		if not canton:
			out["notes"].append(_("The person has no canton of work: the cantonal minimum is not checked."))
		elif rows:
			hours = _month_hours(employee, first, last)
			if hours is None and rules.has("hourly_divisor"):
				hours = flt(rules.get("hourly_divisor")) * rate / 100
			if hours is None:
				out["notes"].append(
					_("The hours of the month are not known: the cantonal minimum is not checked.")
				)
			else:
				out["cantonal"] = {
					"amount": flt(flt(rows[0]["hourly"]) * hours, 2),
					"canton": rows[0]["canton"],
					"hourly": flt(rows[0]["hourly"]),
					"hours": flt(hours, 2),
					"article": rows[0].get("article"),
				}
	elif rules.state("cantonal_minimum_wages") in (TO_CONFIRM, DEDUCED):
		out["notes"].append(_("The cantonal minimum is not confirmed: it checks nothing."))

	if out["agreement"] and person.get(REDUCTION_FIELD):
		out["reduction"] = _reduction(rules, person, employee, first, last, rate, out["agreement"]["amount"])
		if out["reduction"] and out["reduction"]["applied"]:
			out["agreement"]["amount"] = flt(out["agreement"]["amount"] - out["reduction"]["amount"], 2)

	amounts = [part["amount"] for part in (out["agreement"], out["cantonal"]) if part]
	out["amount"] = max(amounts) if amounts else None
	return out


def _reduction(rules, person, employee, first, last, rate, amount) -> dict | None:
	"""The reduction agreed with the person, applied only in a month whose turnover is known and under the threshold."""
	value = rules.get("minimum_wage_reduction")
	if not value:
		return {"applied": False, "amount": 0, "note": _("The reduction of the minimum is not confirmed.")}
	year = completed_years(person.get(EXPERIENCE_FIELD), first) + 1 if person.get(EXPERIENCE_FIELD) else None
	step = next(
		(
			item
			for item in value.get("amounts") or []
			if isinstance(item, dict) and year is not None and int(flt(item.get("experience_year"))) == year
		),
		None,
	)
	if not step:
		return {"applied": False, "amount": 0, "note": _("No reduction for this year of experience.")}
	threshold = flt(value["threshold_monthly"]) * (rate / 100 if value.get("threshold_pro_rata") else 1)
	turnover = _turnover(employee, first, last)
	if turnover is None:
		return {
			"applied": False,
			"amount": flt(step.get("amount")),
			"threshold": threshold,
			"note": _(
				"The reduction applies only in a month whose turnover stays under {0}; the turnover of the month is"
				" not known here: the full minimum is checked."
			).format(_number(threshold)),
		}
	return {
		"applied": turnover < threshold,
		"amount": flt(step.get("amount")),
		"threshold": threshold,
		"turnover": turnover,
		"note": "",
	}


def _number(value) -> str:
	value = flt(value, 2)
	return str(int(value)) if value.is_integer() else f"{value:.2f}"


def counted_components() -> set:
	"""The salary components the client ticked as counting toward the minimum."""
	if not frappe.get_meta("Salary Component").has_field(COUNTS_FIELD):
		return set()
	return set(frappe.get_all("Salary Component", filters={COUNTS_FIELD: 1}, pluck="name"))


def pay_of(employee: str, month, slip=None) -> dict:
	"""The pay of a month that counts toward the minimum: the ticked components on the person's pay slips of the month
	(drafts and submitted, never cancelled). `slip`, a pay slip being saved, counts in place of its stored copy."""
	first = get_first_day(getdate(month))
	last = get_last_day(first)
	ticked = counted_components()
	names = frappe.get_all(
		"Salary Slip",
		filters={"employee": employee, "docstatus": ["<", 2], "start_date": ["between", [first, last]]},
		pluck="name",
	)
	if slip is not None and slip.name in names:
		names.remove(slip.name)
	amount = 0.0
	if names and ticked:
		amount = flt(
			sum(
				flt(row.amount)
				for row in frappe.get_all(
					"Salary Detail",
					filters={
						"parenttype": "Salary Slip",
						"parentfield": "earnings",
						"parent": ["in", names],
						"salary_component": ["in", list(ticked)],
					},
					fields=["amount"],
				)
			)
		)
	if slip is not None:
		names.append(slip.name or _("this pay slip"))
		amount += sum(flt(row.amount) for row in slip.get("earnings") or [] if row.salary_component in ticked)
	return {"amount": flt(amount, 2), "slips": names, "ticked": bool(ticked)}


def check_month(employee: str, month, slip=None) -> dict | None:
	"""A person's month: the minimum due, the pay that counts, and whether it reaches it. None without an agreement."""
	minimum = minimum_of(employee, month)
	if minimum is None:
		return None
	out = {"employee": employee, **minimum, "pay": None, "shortfall": 0.0, "state": NOT_CHECKED}
	if minimum["amount"] is None:
		return out
	rules = rules_for(employee)
	pay = pay_of(employee, month, slip)
	out["pay"] = pay["amount"]
	out["slips"] = pay["slips"]
	if not pay["ticked"]:
		out["notes"].append(
			_("No salary component is ticked as counting toward the minimum: nothing is compared.")
		)
		return out
	if not pay["slips"]:
		out["state"] = NO_PAY
		return out
	due, paid = minimum["amount"], pay["amount"]
	if rules.get("minimum_wage_period") == catalogue.OVER_THE_YEAR:
		due, paid = _year_to_date(employee, minimum["month"], slip)
		out["year_due"], out["year_paid"] = due, paid
	out["shortfall"] = flt(max(due - paid, 0), 2)
	out["state"] = UNDER if out["shortfall"] > 0.005 else REACHED
	return out


def _year_to_date(employee: str, month, slip):
	"""The minimums due and the pay that counts from January to `month`, for a check over the year."""
	due = paid = 0.0
	for number in range(1, month.month + 1):
		first = datetime.date(month.year, number, 1)
		minimum = minimum_of(employee, first)
		due += flt((minimum or {}).get("amount"))
		paid += pay_of(employee, first, slip if number == month.month else None)["amount"]
	return flt(due, 2), flt(paid, 2)


def warn_on_slip(doc, method=None):
	"""On a pay slip's save: a message when the month's pay that counts stays under the minimum. Never a refusal."""
	try:
		if not doc.employee or not doc.start_date:
			return
		found = check_month(doc.employee, doc.start_date, slip=doc)
	except Exception:
		frappe.log_error("Minimum wage check failed on a pay slip", frappe.get_traceback())
		return
	if found and found["state"] == UNDER:
		frappe.msgprint(
			_(
				"The pay that counts toward the minimum ({0}) is under the minimum of {1} for {2}: {3} short."
				" The pay slip is saved as it is; the agreement's minimum is a warning, never a change of the pay."
			).format(
				_number(found["pay"]),
				_number(found["amount"]),
				formatdate(doc.start_date, "MMMM yyyy"),
				_number(found["shortfall"]),
			),
			title=_("Under the minimum wage"),
			indicator="orange",
		)


@frappe.whitelist()
def month_view(month: str | None = None) -> dict:
	"""The check of a month for every active employee tied to an agreement, for the HR staff."""
	from hrms.hr.working_time.agreement import EMPLOYEE_FIELD

	frappe.has_permission("Working Time Week", "read", throw=True)
	first = get_first_day(getdate(month) if month else getdate())
	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active", EMPLOYEE_FIELD: ["is", "set"]},
		fields=["name", "employee_name"],
		order_by="employee_name asc",
	)
	rows = []
	for person in employees:
		found = check_month(person.name, first)
		if found is None:
			continue
		rows.append({**found, "employee_name": person.employee_name})
	return {
		"month": first,
		"employees": rows,
		"under": sum(1 for row in rows if row["state"] == UNDER),
		"not_checked": sum(1 for row in rows if row["state"] == NOT_CHECKED),
	}
