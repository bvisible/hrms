# //// Neoffice — added file (no upstream equivalent): migrates the Swiss Salary Certificate expense
# //// fields from our first simplified layout to the granular Form 11 positions
# //// (13.1.1 travel, 13.2.2 car, 13.2.3 other flat rate).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe


def execute():
	"""Migrate Swiss Salary Certificate expense fields from simplified to granular Form 11 positions.

	Old fields -> New fields:
	- position_13_1_actual_expenses -> position_13_1_1_travel
	- position_13_2_flat_rate_car -> position_13_2_2_car
	- position_13_3_other_flat_expenses -> position_13_2_3_other_flat
	"""
	# //// Neoffice — was table_exists("tabSwiss Salary Certificate"). frappe.db.table_exists
	# //// prepends "tab" itself, so it looked for "tabtabSwiss Salary Certificate", never found
	# //// it, and this patch returned on its first line on every instance of the fleet. It was
	# //// logged as executed all the same, hence the re-run entry in patches.txt.
	if not frappe.db.table_exists("Swiss Salary Certificate"):
		return

	old_columns = frappe.db.get_table_columns("Swiss Salary Certificate")
	if "position_13_1_actual_expenses" not in old_columns:
		return

	# //// Neoffice — each column only fills where nothing was entered. The patch never ran (see
	# //// above), so it runs today on certificates that have lived months in the new layout: an
	# //// unconditional copy would overwrite an amount somebody typed with the stale old column.
	# Migrate data from old fields to new fields
	frappe.db.sql("""
		UPDATE `tabSwiss Salary Certificate`
		SET
			-- //// Neoffice — fill only where nothing was entered, see above.
			position_13_1_1_travel = IF(
				IFNULL(position_13_1_1_travel, 0) = 0,
				IFNULL(position_13_1_actual_expenses, 0),
				position_13_1_1_travel
			),
			position_13_2_2_car = IF(
				IFNULL(position_13_2_2_car, 0) = 0,
				IFNULL(position_13_2_flat_rate_car, 0),
				position_13_2_2_car
			),
			position_13_2_3_other_flat = IF(
				IFNULL(position_13_2_3_other_flat, 0) = 0,
				IFNULL(position_13_3_other_flat_expenses, 0),
				position_13_2_3_other_flat
			)
		WHERE
			position_13_1_actual_expenses > 0
			OR position_13_2_flat_rate_car > 0
			OR position_13_3_other_flat_expenses > 0
	""")
