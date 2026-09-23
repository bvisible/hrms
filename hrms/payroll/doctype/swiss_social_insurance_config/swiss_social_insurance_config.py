# //// Neoffice — added file (no upstream equivalent): controller of the per-company Swiss social
# //// insurance configuration (AVS/AC/LAA/IJM/LPP rates, ceilings, Lohnausweis header,
# //// payment account).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SwissSocialInsuranceConfig(Document):
	def validate(self):
		self.validate_lpp_employer_share()
		self.validate_rates()
		self.set_default()

	def set_default(self):
		"""A company's first configuration is its default one.

		Every lookup without a canton — the monthly cycle's preflight, the salary payment file,
		the salary certificate header, the Swissdec declarations — reads the default
		configuration only. Nothing ever set it: a company configured through the onboarding
		failed its first payroll run with "no configuration".
		"""
		if self.is_default or not self.company:
			return
		other_default = frappe.db.exists(
			"Swiss Social Insurance Config",
			{"company": self.company, "is_default": 1, "name": ("!=", self.name or "")},
		)
		if not other_default:
			self.is_default = 1

	def on_update(self):
		# One default per company: marking this one unmarks the others.
		if self.is_default:
			for name in frappe.get_all(
				"Swiss Social Insurance Config",
				filters={"company": self.company, "is_default": 1, "name": ("!=", self.name)},
				pluck="name",
			):
				frappe.db.set_value("Swiss Social Insurance Config", name, "is_default", 0)

	def validate_lpp_employer_share(self):
		if self.lpp_employer_share_pct and self.lpp_employer_share_pct < 50:
			frappe.throw(_("LPP Employer Share must be at least 50% as required by Swiss law."))

	def validate_rates(self):
		# Ensure all percentage fields are between 0 and 100
		rate_fields = [
			"avs_rate_employee",
			"avs_rate_employer",
			"ac_rate_employee",
			"ac_rate_employer",
			"ac_solidarity_rate_employee",
			"ac_solidarity_rate_employer",
			"laa_professional_rate",
			"laa_nonprofessional_rate",
			"ijm_rate_employee",
			"ijm_rate_employer",
			"family_allowance_rate",
			"lpp_employer_share_pct",
		]
		for field in rate_fields:
			value = self.get(field) or 0
			if value < 0 or value > 100:
				frappe.throw(_("{0} must be between 0 and 100.").format(self.meta.get_label(field)))
