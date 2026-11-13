# //// Neoffice — added file (no upstream equivalent): the monthly statement of the hours, established by the
# //// employer, countersigned or remarked by the employee, read by each one for themselves only (lot T, #2623).
"""The statement of a month: what the employer establishes and the employee countersigns.

`establish_statement` (HR manager) adds up the weeks kept whose Monday falls in the month, the hours that fell
due for payment in it and the balance at its end; the copy is in the employee's space from that moment. A
statement the employee countersigned is never established again: a correction goes into the next month.

`countersign_statement` and `add_remark` are the employee's own gestures: nobody signs or remarks in their place,
not even the HR manager. A remark waits for its answer (`answer_remark`, HR manager) before the employee
countersigns. The employee reads their own statements only (`has_permission`, `get_permission_query_conditions`,
the same pattern as the Swiss salary certificate), never a colleague's.
"""

import datetime
import json

import frappe
from frappe import _
from frappe.utils import flt, get_last_day, getdate, now_datetime

from hrms.hr.working_time.agreement import EMPLOYEE_FIELD, rules_for
from hrms.hr.working_time.store import WEEK_DOCTYPE, balance_of, counted_over

STATEMENT_DOCTYPE = "Working Time Statement"
ESTABLISHED, REMARK, COUNTERSIGNED = "Established", "Remark", "Countersigned"
STAFF_ROLES = ("HR Manager", "HR User")
SUMMED = ("due", "done", "credited", "short")


def _is_staff(user):
	return user == "Administrator" or bool(set(STAFF_ROLES) & set(frappe.get_roles(user)))


def _employees_of(user):
	return frappe.get_all("Employee", filters={"user_id": user}, pluck="name")


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Staff: the roles decide. An employee: their own statements, to read and print, never a colleague's."""
	user = user or frappe.session.user
	if _is_staff(user):
		return None
	if ptype not in (None, "read", "print"):
		return False
	return doc.employee in _employees_of(user)


def get_permission_query_conditions(user=None, doctype=None):
	user = user or frappe.session.user
	if _is_staff(user):
		return ""
	employees = _employees_of(user)
	if not employees:
		return "1=0"
	names = ", ".join(frappe.db.escape(name) for name in employees)
	return f"`tab{STATEMENT_DOCTYPE}`.employee in ({names})"


@frappe.whitelist()
def establish_statement(employee: str, month) -> str:
	"""Establish (or establish again, until countersigned) an employee's statement of a month. Returns its name."""
	# the engine creates statements (in_create): establishing one is the HR manager's, who may write them
	frappe.has_permission(STATEMENT_DOCTYPE, "write", throw=True)
	if not frappe.db.exists("Employee", employee):
		frappe.throw(_("There is no employee {0}.").format(employee))
	if not frappe.db.get_value("Employee", employee, EMPLOYEE_FIELD):
		frappe.throw(
			_("{0} is tied to no labour agreement: there is no statement of their hours.").format(employee)
		)
	first = getdate(month).replace(day=1)
	last = getdate(get_last_day(first))
	name = frappe.db.get_value(STATEMENT_DOCTYPE, {"employee": employee, "month": first})
	doc = frappe.get_doc(STATEMENT_DOCTYPE, name) if name else frappe.new_doc(STATEMENT_DOCTYPE)
	if doc.status == COUNTERSIGNED:
		frappe.throw(
			_("This statement was countersigned: a correction goes into the next month's statement.")
		)
	weeks = frappe.get_all(
		WEEK_DOCTYPE,
		filters={"employee": employee, "monday": ["between", [first, last]]},
		fields=[
			"monday",
			"due",
			"done",
			"credited",
			"over",
			"short",
			"needs_approval",
			"approved_hours",
			"approved_by",
		],
		order_by="monday asc",
	)
	rules = rules_for(employee)
	doc.employee = employee
	doc.month = first
	doc.period_start, doc.period_end = first, last
	doc.agreement = frappe.db.get_value("Employee", employee, EMPLOYEE_FIELD)
	for field in SUMMED:
		doc.set(field, flt(sum(abs(flt(week.get(field))) for week in weeks), 4))
	doc.over = flt(sum(counted_over(week) for week in weeks), 4)
	doc.weeks_count = len(weeks)
	doc.weeks = json.dumps([{**week, "counted_over": counted_over(week)} for week in weeks], default=str)
	balance = balance_of(employee, last)
	payable = [item for item in (balance.payable if balance else []) if first <= getdate(item["on"]) <= last]
	doc.paid_hours = flt(sum(flt(item["hours"]) for item in payable), 4)
	doc.payable = json.dumps(payable, default=str)
	doc.balance_end = flt(balance.total, 4) if balance else 0
	expiries = [lot["expires"] for lot in (balance.lots if balance else []) if lot.get("expires")]
	doc.next_expiry = min(expiries) if expiries else None
	years = rules.get("retention_years") if rules else None
	doc.retention_until = datetime.date(first.year + int(years), 12, 31) if years else None
	doc.countersign_expected = 1 if rules and rules.get("employee_countersigns") else 0
	doc.status = ESTABLISHED
	doc.established_by = frappe.session.user
	doc.established_on = now_datetime()
	doc.copy_given_on = doc.established_on
	doc.remark = doc.remark_on = doc.remark_answer = doc.answered_by = doc.answered_on = None
	doc.flags.ignore_permissions = True
	doc.save() if name else doc.insert()
	return doc.name


def _own(statement: str):
	"""The statement, when the person asking is its employee; nobody acts in their place."""
	doc = frappe.get_doc(STATEMENT_DOCTYPE, statement)
	if doc.employee not in _employees_of(frappe.session.user):
		raise frappe.PermissionError(_("Only the employee of a statement countersigns it or makes a remark."))
	return doc


@frappe.whitelist()
def countersign_statement(statement: str) -> dict:
	"""The employee countersigns their own statement: the person and the moment are kept."""
	doc = _own(statement)
	if doc.status == COUNTERSIGNED:
		frappe.throw(_("This statement is already countersigned."))
	if doc.status == REMARK:
		frappe.throw(
			_("Your remark is waiting for its answer: the statement is countersigned once it is answered.")
		)
	doc.status = COUNTERSIGNED
	doc.countersigned_by = frappe.session.user
	doc.countersigned_on = now_datetime()
	doc.flags.ignore_permissions = True
	doc.save()
	return {"statement": doc.name, "by": doc.countersigned_by, "on": str(doc.countersigned_on)}


@frappe.whitelist()
def add_remark(statement: str, text: str) -> dict:
	"""The employee leaves a remark on their own statement; it waits for the employer's answer."""
	doc = _own(statement)
	if doc.status == COUNTERSIGNED:
		frappe.throw(_("This statement is already countersigned."))
	if not (text or "").strip():
		frappe.throw(_("Write the remark."))
	doc.status = REMARK
	doc.remark = text.strip()
	doc.remark_on = now_datetime()
	doc.remark_answer = doc.answered_by = doc.answered_on = None
	doc.flags.ignore_permissions = True
	doc.save()
	return {"statement": doc.name, "status": doc.status}


@frappe.whitelist()
def answer_remark(statement: str, text: str) -> dict:
	"""The employer answers a remark; the employee can then countersign."""
	doc = frappe.get_doc(STATEMENT_DOCTYPE, statement)
	doc.check_permission("write")
	if doc.status != REMARK:
		frappe.throw(_("This statement has no remark waiting for an answer."))
	doc.remark_answer = (text or "").strip()
	doc.answered_by = frappe.session.user
	doc.answered_on = now_datetime()
	doc.status = ESTABLISHED
	doc.save()
	return {"statement": doc.name, "status": doc.status}
