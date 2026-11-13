# //// Neoffice — added file (no upstream equivalent): the closing of a yearly balance of hours, where the employer
# //// decides for their share and the employee for theirs (lot T, neoffice-maintenance#2623).
"""The closing of an annual balance: each side decides what becomes of its share of the hours over.

At the agreement's closing day a positive balance is shared out (half for the employer, half for the employee,
say). Each side picks one of the agreement's choices for its own share: leave the hours on the account, pay them
with a supplement, move them to a long-term account. `record_closings` writes the closings the balance reached,
with the hours, the shares and the choices of the agreement, and never touches a share already decided.

`decide_employer_share` is the employer's (who may write the closing: the HR manager); `decide_employee_share` is
the employee's own gesture: nobody decides in their place, not even the HR manager. A decision is a person and a
moment and is not changed afterwards. `decisions_of` gives the decided shares to the balance, which takes the
paid and moved hours out of it at the closing day: a paid share becomes a line to pay, with its supplement.
The employee reads their own closings only (`has_permission`, `get_permission_query_conditions`).
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

from hrms.hr.working_time.agreement import EMPLOYEE_FIELD
from hrms.hr.working_time.statement import _employees_of, _is_staff

CLOSING_DOCTYPE = "Working Time Closing"
WAITING, DECIDED = "Waiting", "Decided"
SIDES = ("employer", "employee")


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Staff: the roles decide. An employee: their own closings, to read and print, never a colleague's."""
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
	return f"`tab{CLOSING_DOCTYPE}`.employee in ({names})"


def options_of(decision) -> list:
	"""The agreement's choices as {label, action, supplement_percent}; a bare text is only recorded."""
	options = []
	for option in (decision or {}).get("options") or []:
		if isinstance(option, dict):
			options.append(option)
		else:
			options.append({"label": str(option), "action": None})
	return options


def record_closings(employee: str, on_date) -> list:
	"""Write the closings of an employee's annual balance reached by `on_date`; the names written."""
	from hrms.hr.working_time.agreement import rules_for
	from hrms.hr.working_time.store import balance_of

	rules = rules_for(employee)
	balance = balance_of(employee, on_date)
	if rules is None or balance is None:
		return []
	options = options_of(rules.get("closing_decision"))
	written = []
	for closing in balance.closings:
		hours = flt(closing["hours"], 4)
		if hours <= 0:
			continue
		name = frappe.db.get_value(CLOSING_DOCTYPE, {"employee": employee, "closing_date": closing["on"]})
		doc = frappe.get_doc(CLOSING_DOCTYPE, name) if name else frappe.new_doc(CLOSING_DOCTYPE)
		if doc.employer_choice or doc.employee_choice:
			continue
		doc.employee = employee
		doc.closing_date = closing["on"]
		doc.agreement = frappe.db.get_value("Employee", employee, EMPLOYEE_FIELD)
		doc.hours = hours
		doc.employer_hours = flt(hours * flt(closing.get("employer_share")), 4)
		doc.employee_hours = flt(hours * flt(closing.get("employee_share")), 4)
		doc.options = json.dumps(options, ensure_ascii=False)
		doc.status = WAITING
		doc.flags.ignore_permissions = True
		doc.save() if name else doc.insert()
		written.append(doc.name)
	return written


def _decide(doc, side: str, choice: str) -> dict:
	if doc.get(f"{side}_choice"):
		frappe.throw(_("This share of the closing is already decided."))
	labels = [option["label"] for option in json.loads(doc.options or "[]")]
	if choice not in labels:
		frappe.throw(_("Choose one of the agreement's choices for this share."))
	doc.set(f"{side}_choice", choice)
	doc.set(f"{side}_by", frappe.session.user)
	doc.set(f"{side}_on", now_datetime())
	doc.status = DECIDED if all(doc.get(f"{each}_choice") for each in SIDES) else WAITING
	doc.flags.ignore_permissions = True
	doc.save()
	return {"closing": doc.name, "status": doc.status}


@frappe.whitelist()
def decide_employer_share(closing: str, choice: str) -> dict:
	"""The employer decides what becomes of their share of the closing."""
	doc = frappe.get_doc(CLOSING_DOCTYPE, closing)
	doc.check_permission("write")
	return _decide(doc, "employer", choice)


@frappe.whitelist()
def decide_employee_share(closing: str, choice: str) -> dict:
	"""The employee decides what becomes of their own share; nobody decides in their place."""
	doc = frappe.get_doc(CLOSING_DOCTYPE, closing)
	if doc.employee not in _employees_of(frappe.session.user):
		raise frappe.PermissionError(_("Only the employee of a closing decides their share."))
	return _decide(doc, "employee", choice)


def decisions_of(employee: str) -> dict:
	"""{closing day: [{"hours", "action", "supplement_percent"}, …]}: the decided shares of an employee."""
	decided = {}
	for row in frappe.get_all(
		CLOSING_DOCTYPE,
		filters={"employee": employee},
		fields=[
			"closing_date",
			"options",
			*[f"{side}_{field}" for side in SIDES for field in ("hours", "choice")],
		],
	):
		options = {option["label"]: option for option in json.loads(row.options or "[]")}
		for side in SIDES:
			option = options.get(row.get(f"{side}_choice"))
			if option:
				decided.setdefault(getdate(row.closing_date), []).append(
					{
						"hours": flt(row.get(f"{side}_hours")),
						"action": option.get("action"),
						"supplement_percent": option.get("supplement_percent"),
					}
				)
	return decided
