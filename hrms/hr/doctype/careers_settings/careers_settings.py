# //// Neoffice — added file (no upstream equivalent): the settings of the careers page (careers page, neoffice-maintenance#1294).

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class CareersSettings(Document):
	"""The settings of the careers page (hrms.hr.careers).

	The page itself is switched on in the website's plugins (Jobs); accepting unsolicited
	applications opens it even without a published opening, so the menu follows this form too.
	"""

	def validate(self):
		if cint(self.retention_days) < 1:
			frappe.throw(_("Applications must be deleted at least one day after the decision."))
		if cint(self.talent_pool_months) < 1:
			self.talent_pool_months = 12

	def on_update(self):
		from hrms.hr.careers.plugin import sync_menu

		sync_menu()
