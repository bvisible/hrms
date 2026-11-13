# //// Neoffice — added file (no upstream equivalent): the two vacation settings of the Swiss Social Insurance
# //// Config show, on the configurations that already exist, the values the code applied until now (lot T).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""12 months for the average of the variable pay, 20 vacation days a year when none is allocated: the code fell back
on these two numbers when nothing was set, so writing them into the empty fields changes no payment. It shows the
client the value in use, with its source in the field's description, where it can change it."""

import frappe

DOCTYPE = "Swiss Social Insurance Config"
VALUES = {"vacation_average_months": 12, "default_vacation_days": 20}


def execute():
	for field, value in VALUES.items():
		if not frappe.db.has_column(DOCTYPE, field):
			continue
		frappe.db.sql(
			f"UPDATE `tab{DOCTYPE}` SET `{field}` = %s WHERE IFNULL(`{field}`, 0) = 0",  # nosemgrep
			(value,),
		)
