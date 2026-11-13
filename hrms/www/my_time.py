# //// Neoffice — added file (no upstream equivalent): the employee's own page of their working time, where they read,
# //// countersign or remark their monthly statements (lot T, neoffice-maintenance#2623).
"""/my-time: the monthly statements of the person signed in, never a colleague's (hr/working_time/views.py)."""

import frappe
from frappe import _

no_cache = 1


def hours_minutes(hours, signed=False) -> str:
	"""Hours as « 2 h 33 »; signed, with a plus or a minus sign before them."""
	value = float(hours or 0)
	minutes = round(abs(value) * 60)
	text = f"{minutes // 60} h {minutes % 60:02d}"
	if signed and minutes:
		return ("− " if value < 0 else "+ ") + text
	return text


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/my-time"
		raise frappe.Redirect
	from hrms.hr.working_time.views import my_statements

	data = my_statements()
	context.no_cache = 1
	context.show_sidebar = False
	context.title = _("My working time")
	context.statements = data["statements"]
	context.no_employee = not data["employees"]
	context.hm = hours_minutes
	return context
