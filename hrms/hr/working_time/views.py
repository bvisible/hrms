# //// Neoffice — added file (no upstream equivalent): what the working-time screens read, in words, with the
# //// rights checked on the server (lot T, neoffice-maintenance#2623).
"""What the screens of the working time show, read on the server with the reader's rights.

`describe` writes a line's value in words, in the reader's language ("43 h", "6 months", "25 %", the rows of a
table); the screens never read the stored JSON. `agreement_view` gives an agreement as its screen shows it: the
lines grouped as the catalogue groups them, each with its value in words, its source and its state, the employees
tied to it and the journal of the confirmations. `attach_employees` ties employees to an agreement, the HR
manager's gesture of the screen and of the template's dialog.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from hrms.hr.working_time import rules as catalogue
from hrms.hr.working_time.agreement import (
	CONFIRMED,
	DEDUCED,
	DOCTYPE,
	EMPLOYEE_FIELD,
	NOT_FOUND,
	TO_CONFIRM,
)


def _number(value) -> str:
	value = flt(value)
	return str(int(value)) if value.is_integer() else f"{value:g}"


def _amount(kind: str, value) -> str:
	number = _number(value)
	if kind == "hours":
		return _("{0} h").format(number)
	if kind == "percent":
		return _("{0} %").format(number)
	if kind == "months":
		return _("{0} months").format(number) if flt(value) != 1 else _("1 month")
	if kind == "weeks":
		return _("{0} weeks").format(number) if flt(value) != 1 else _("1 week")
	if kind == "days":
		return _("{0} days").format(number) if flt(value) != 1 else _("1 day")
	if kind == "years":
		return _("{0} years").format(number) if flt(value) != 1 else _("1 year")
	return number


def _month_day(value: str) -> str:
	month, day = value.split("-")
	return f"{day}.{month}"


def _vacation_row(row) -> str:
	days = _("{0} days").format(_number(row["days"]))
	parts = []
	if row.get("age_from") is not None:
		parts.append(_("from {0}").format(_number(row["age_from"])))
	if row.get("age_to") is not None:
		parts.append(_("until {0}").format(_number(row["age_to"])))
	if row.get("years_in_company_from"):
		parts.append(_("after {0} years in the company").format(_number(row["years_in_company_from"])))
	return " ".join([days, *parts])


def _time_range_row(row) -> str:
	if row.get("amount_per_hour") is not None:
		rate = _("{0} an hour").format(_number(row["amount_per_hour"]))
	else:
		rate = _("{0} %").format(_number(row.get("percent") or 0))
	return f"{row.get('label') or ''}: {rate}"


def _object(key: str, value: dict) -> str:
	if key == "conditional_supplement":
		return _("{0} % when its conditions are met, {1} % otherwise").format(
			_number(value["percent_if_met"]), _number(value["percent_otherwise"])
		)
	if key == "closing_decision":
		choices = [
			option["label"] if isinstance(option, dict) else str(option)
			for option in value.get("options") or []
		]
		shares = _("The employer decides {0} %, the employee {1} %").format(
			_number(flt(value["employer_share"]) * 100), _number(flt(value["employee_share"]) * 100)
		)
		return " · ".join([shares, *choices])
	if key == "payment_above_ceiling":
		parts = [value.get("timing") or ""]
		if value.get("paid_hours_before_supplement") is not None:
			parts.append(
				_("{0} h a year without supplement, then {1} %").format(
					_number(value["paid_hours_before_supplement"]),
					_number(value.get("supplement_percent") or 0),
				)
			)
		return " · ".join(part for part in parts if part)
	if key == "constant_planning":
		parts = [_("{0} h a day").format(_number(value["daily_hours"]))]
		if value.get("workdays_per_week"):
			parts.append(_("{0} days a week").format(_number(value["workdays_per_week"])))
		if value.get("first_date"):
			parts.append(_("from {0}").format(frappe.format(value["first_date"], {"fieldtype": "Date"})))
		return " · ".join(parts)
	if key == "travel_time":
		return value.get("paid") or ""
	texts = [str(item) for item in value.values() if isinstance(item, str)]
	return " · ".join(texts)


def describe(key: str, value) -> str:
	"""A line's value in words, in the reader's language; "" for an empty line."""
	if value in (None, "", []):
		return ""
	spec = catalogue.rule(key)
	if spec.kind in catalogue.NUMBER_KINDS:
		return _amount(spec.kind, value)
	if spec.kind == "choice":
		return _(value)
	if spec.kind == "bool":
		return _("Yes") if value else _("No")
	if spec.kind == "month_day":
		return _month_day(value)
	if spec.kind == "text":
		return value
	if spec.kind == "object":
		return _object(key, value)
	if key == "vacation_entitlement":
		return " · ".join(_vacation_row(row) for row in value)
	if key == "time_range_supplements":
		return " · ".join(_time_range_row(row) for row in value)
	if key == "company_status_hours":
		return " · ".join(f"{row['status']}: {_amount('hours', row['hours'])}" for row in value)
	if key == "annual_calendar":
		return " · ".join(
			f"{frappe.format(row['from'], {'fieldtype': 'Date'})} – "
			f"{frappe.format(row['to'], {'fieldtype': 'Date'})}: {_amount('hours', row['hours'])}"
			for row in value
		)
	return " · ".join(" ".join(str(item) for item in row.values()) for row in value)


STATE_LABELS = {
	CONFIRMED: "Confirmed",
	TO_CONFIRM: "To confirm",
	DEDUCED: "Deduced, to check",
	NOT_FOUND: "Not found",
}


@frappe.whitelist()
def agreement_view(agreement: str) -> dict:
	"""An agreement as its screen shows it, read with the reader's rights."""
	doc = frappe.get_doc(DOCTYPE, agreement)
	doc.check_permission("read")
	groups, journal = {}, []
	for row in doc.rules:
		spec = catalogue.rule(row.rule)
		try:
			value = catalogue.parse(row.rule, row.value)
		except ValueError:
			value = None
		groups.setdefault(spec.group, []).append(
			{
				"name": row.name,
				"rule": row.rule,
				"label": _(spec.label.msg),
				"value": describe(row.rule, value),
				"source": row.source_title or "",
				"article": row.source_article or "",
				"version": row.source_version or "",
				"url": row.source_url or "",
				"read_on": row.read_on,
				"state": row.state,
				# a line is feminine in French (« confirmée »): the bare word of another app would not agree
				"state_label": _(
					STATE_LABELS.get(row.state, row.state or ""), context="Labour Agreement Rule"
				),
				"confirmed_by": frappe.utils.get_fullname(row.confirmed_by) if row.confirmed_by else "",
				"confirmed_on": row.confirmed_on,
				"note": row.note or "",
				"confirmable": row.state in (TO_CONFIRM, DEDUCED)
				and bool(row.value)
				and bool(row.source_title),
			}
		)
		if row.state == CONFIRMED and row.confirmed_on:
			journal.append(
				{
					"label": _(spec.label.msg),
					"by": frappe.utils.get_fullname(row.confirmed_by),
					"on": row.confirmed_on,
				}
			)
	employees = frappe.get_all(
		"Employee",
		filters={EMPLOYEE_FIELD: agreement},
		fields=["name", "employee_name", "status"],
		order_by="employee_name asc",
	)
	states = [row.state for row in doc.rules]
	expires = getdate(doc.template_expires_on) if doc.template_expires_on else None
	return {
		"name": doc.name,
		"title": doc.agreement_name,
		"kind": _(doc.kind) if doc.kind else "",
		"company": doc.company,
		"template": doc.template,
		"template_version": doc.template_version,
		"template_expires_on": doc.template_expires_on,
		"expired": bool(expires and expires < getdate(nowdate())),
		"read_on": max((row.read_on for row in doc.rules if row.read_on), default=None),
		"total": len(states),
		"confirmed": states.count(CONFIRMED),
		"to_confirm": len([row for group in groups.values() for row in group if row["confirmable"]]),
		"groups": [
			{"key": key, "label": _(catalogue.GROUPS[key].msg), "rows": rows}
			for key in catalogue.GROUPS
			if (rows := groups.get(key))
		],
		"employees": employees,
		"journal": sorted(journal, key=lambda item: item["on"], reverse=True),
		"can_write": doc.has_permission("write"),
	}


@frappe.whitelist()
def attach_employees(agreement: str, employees: str | list | None = None, all_active: int = 0) -> dict:
	"""Tie employees to an agreement: those named, or every active employee of the agreement's company."""
	doc = frappe.get_doc(DOCTYPE, agreement)
	doc.check_permission("read")
	if isinstance(employees, str):
		employees = frappe.parse_json(employees)
	if frappe.utils.cint(all_active):
		filters = {"status": "Active"}
		if doc.company:
			filters["company"] = doc.company
		employees = frappe.get_all("Employee", filters=filters, pluck="name")
	tied = []
	for employee in employees or []:
		person = frappe.get_doc("Employee", employee)
		person.check_permission("write")
		person.db_set(EMPLOYEE_FIELD, agreement)
		tied.append(employee)
	return {"agreement": agreement, "employees": tied}
