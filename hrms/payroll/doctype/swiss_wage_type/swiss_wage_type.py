#//// Neoffice — added file (no upstream equivalent): controller of the Swissdec wage type catalog
#//// entry (code + which social insurance bases it feeds).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SwissWageType(Document):
	def validate(self):
		self._validate_code_format()

	def _validate_code_format(self):
		"""Ensure code is numeric and within valid range."""
		if not self.code or not self.code.strip().isdigit():
			frappe.throw(_("Code must be a numeric value (e.g., 1000, 5010)"))
