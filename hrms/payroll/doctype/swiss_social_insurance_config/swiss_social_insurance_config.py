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
