# //// Neoffice — added file (no upstream equivalent): the verify_tls Check added to Swissdec
# //// Transmitter Settings ships with default 1, but a doctype default never reaches a Single that
# //// is ALREADY stored — the row simply holds no value, the desk renders the box unchecked, and
# //// the next save of the form would persist a 0 and silently turn TLS verification off again.
# //// Write the 1 once, and only where nobody has chosen yet.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe


def execute():
	"""Turn TLS verification on for Swissdec settings stored before the field existed."""
	if not frappe.db.exists("DocType", "Swissdec Transmitter Settings"):
		return

	stored = frappe.db.sql(
		"""SELECT `value` FROM `tabSingles` WHERE `doctype` = %s AND `field` = %s""",
		("Swissdec Transmitter Settings", "verify_tls"),
	)
	if stored:
		return

	frappe.db.set_single_value("Swissdec Transmitter Settings", "verify_tls", 1)
