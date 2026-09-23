# //// Neoffice — added file (no upstream equivalent): who may read the payroll of a whole company
# //// through the Swiss endpoints (year-end closing, monthly cycle).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.core.doctype.user_permission.user_permission import get_user_permissions

PAYROLL_STAFF_ROLES = ("HR Manager", "HR User", "System Manager")


def check_payroll_staff(company=None):
	"""Refuse anyone but payroll staff who see every employee — of ``company`` when given.

	The Swiss endpoints read every slip of a company through frappe.get_all / frappe.db.sql, which
	bypass permissions. frappe.has_permission("Salary Slip", "read") is no gate for that: the
	Employee role has it (for their own slips, through a User Permission the query ignores), so an
	ordinary employee received every colleague's pay, AVS number, birth date and tariff code.
	"""
	user = frappe.session.user
	if user == "Administrator":
		return
	if not set(frappe.get_roles(user)) & set(PAYROLL_STAFF_ROLES):
		frappe.throw(
			_("Only payroll staff can see the payroll of the whole company."), frappe.PermissionError
		)
	# Staff limited to some employees by a User Permission see those in the lists, not the rest.
	restrictions = get_user_permissions(user).get("Employee") or []
	if any(r.get("applicable_for") in (None, "", "Salary Slip") for r in restrictions):
		frappe.throw(
			_(
				"Your access is limited to some employees: it does not cover the payroll of the whole company."
			),
			frappe.PermissionError,
		)
	check_company_access(company)
	frappe.has_permission("Salary Slip", "read", throw=True)


def check_company_access(company):
	"""Refuse a company outside the caller's User Permissions on Company.

	Not has_permission("Company", "read", doc=...): HR User and HR Manager have no role permission
	on Company, and a payroll administrator who is not an employee would be locked out. What
	matters is the restriction: staff limited to company A must not act on company B."""
	user = frappe.session.user
	if not company or user == "Administrator":
		return
	allowed = [
		r["doc"]
		for r in get_user_permissions(user).get("Company") or []
		if r.get("applicable_for") in (None, "", "Salary Slip")
	]
	if allowed and company not in allowed:
		frappe.throw(_("You have no access to the company {0}.").format(company), frappe.PermissionError)
