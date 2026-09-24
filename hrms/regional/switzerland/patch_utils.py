# //// Neoffice — added file (no upstream equivalent): the guard the Swiss payroll patches share.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""What a Swiss payroll patch checks before it reads the payroll's own columns.

hooks.after_migrate creates the Swiss custom fields on every site (setup.make_custom_fields), but
it runs AFTER the patches. On the first migrate of a site that never had them, a patch reading
Salary Component.ch_wage_type_code — or any Swiss column of a standard DocType — meets a column
that does not exist yet, and `bench migrate` aborts (a canary instance without the Swiss
payroll, 2026-09-24, neoffice-maintenance#722). Without the column there is no Swiss component,
employee or slip for the patch to correct: it has nothing to do there.

The patches that only maintain hrms's own Swiss DocTypes (the wage type catalogue, the QST tariff
tables, the salary certificate) need no guard: those tables exist on every site, and an index or a
correction made there is in place the day the site sets the payroll up.
"""

import frappe


def has_swiss_columns(doctype, *columns):
	"""Whether every one of ``columns`` (Swiss custom fields) exists on ``doctype`` yet."""
	return all(frappe.db.has_column(doctype, column) for column in columns)
