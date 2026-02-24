# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from hrms.regional.switzerland.constants import POSITION_FIELD_MAP
from hrms.regional.switzerland.utils import get_swiss_social_insurance_config


class SwissSalaryCertificate(Document):
	def validate(self):
		self.calculate_totals()

	def calculate_totals(self):
		"""Compute positions 8 (gross) and 11 (net) from component positions."""
		# Position 8 = sum of positions 1-7
		self.position_8_gross_income = flt(
			flt(self.position_1_salary)
			+ flt(self.position_2_1_other_benefits)
			+ flt(self.position_2_2_board_lodging)
			+ flt(self.position_2_3_other_fringe)
			+ flt(self.position_3_irregular_benefits)
			+ flt(self.position_4_capital_benefits)
			+ flt(self.position_5_ownership_rights)
			+ flt(self.position_6_board_of_directors)
			+ flt(self.position_7_other_income),
			2,
		)

		# Position 11 = 8 - 9 - 10.1 - 10.2
		self.position_11_net_salary = flt(
			flt(self.position_8_gross_income)
			- flt(self.position_9_avs_ac_aanp)
			- flt(self.position_10_1_bvg_regular)
			- flt(self.position_10_2_bvg_buyback),
			2,
		)

	@frappe.whitelist()
	def populate_from_salary_slips(self):
		"""Populate certificate positions from submitted salary slips.

		Fetches all submitted Salary Slips for the employee/fiscal year,
		loads the Lohnausweis mapping from Swiss Social Insurance Config,
		and aggregates amounts by position.
		"""
		if not self.employee or not self.fiscal_year:
			frappe.throw(_("Employee and Fiscal Year are required."))

		fiscal_year = frappe.get_doc("Fiscal Year", self.fiscal_year)
		year_start = fiscal_year.year_start_date
		year_end = fiscal_year.year_end_date

		# Fetch submitted salary slips
		slips = frappe.get_all(
			"Salary Slip",
			filters={
				"employee": self.employee,
				"company": self.company,
				"start_date": [">=", year_start],
				"end_date": ["<=", year_end],
				"docstatus": 1,
			},
			pluck="name",
		)

		if not slips:
			frappe.msgprint(
				_("No submitted salary slips found for {0} in {1}.").format(
					self.employee_name, self.fiscal_year
				)
			)
			return

		# Get component amounts from all slips
		slips_data = _get_slips_component_totals(slips)

		# Get position mapping from config
		employee = frappe.get_cached_doc("Employee", self.employee)
		canton = employee.get("ch_fiscal_canton") or ""
		config = get_swiss_social_insurance_config(self.company, canton)

		position_map = {}
		if config:
			config_doc = frappe.get_doc("Swiss Social Insurance Config", config.name)
			for row in config_doc.get("lohnausweis_mapping") or []:
				if row.include_in_certificate:
					position_map[row.salary_component] = row.lohnausweis_position

		# Aggregate into positions
		position_totals = aggregate_salary_slips_for_lohnausweis(slips_data, position_map)

		# Set field values
		for position, amount in position_totals.items():
			field = POSITION_FIELD_MAP.get(position)
			if field and hasattr(self, field):
				self.set(field, flt(amount, 2))

		self.calculate_totals()

		# Auto-generate remarks
		remarks = []
		remarks.append(
			_("Generated from {0} salary slips for fiscal year {1}.").format(len(slips), self.fiscal_year)
		)
		if not position_map:
			remarks.append(_("Warning: No Lohnausweis mapping found in Swiss Social Insurance Config."))
		self.position_15_remarks = "\n".join(remarks)

		frappe.msgprint(_("Certificate populated from {0} salary slips.").format(len(slips)))

	@frappe.whitelist()
	def get_barcode_data(self):
		"""Generate eCH-0270 barcode data for this certificate.

		Returns a dict with base64-encoded PDF417 and CODE128C barcode images
		for embedding in the print format.
		"""
		from hrms.regional.switzerland.lohnausweis_barcode import generate_barcode_page_data

		# Collect employer info
		config = get_swiss_social_insurance_config(self.company)
		company = frappe.get_cached_doc("Company", self.company)

		employer_data = {
			"name": (config and config.get("lohnausweis_employer_name")) or self.company,
			"address": (config and config.get("lohnausweis_employer_address")) or "",
			"uid_bfs": company.get("tax_id") or "",
			"zip_code": company.get("pincode") or "",
			"city": company.get("city") or "",
		}

		# Collect employee info
		employee_data = {
			"name": self.employee_name,
			"avs_number": self.avs_number or "",
			"date_of_birth": str(self.date_of_birth) if self.date_of_birth else "",
			"date_of_joining": str(self.date_of_joining) if self.date_of_joining else "",
			"relieving_date": str(self.relieving_date) if self.relieving_date else "",
		}

		# Collect all positions
		positions = {}
		for pos_key, field_name in POSITION_FIELD_MAP.items():
			positions[pos_key] = flt(self.get(field_name), 2)
		# Computed positions (not in POSITION_FIELD_MAP)
		positions["8"] = flt(self.position_8_gross_income, 2)
		positions["11"] = flt(self.position_11_net_salary, 2)
		positions["15"] = self.position_15_remarks or ""

		certificate_data = {
			"employer": employer_data,
			"employee": employee_data,
			"fiscal_year": str(self.fiscal_year),
			"posting_date": str(self.posting_date) if self.posting_date else "",
			"positions": positions,
		}

		return generate_barcode_page_data(certificate_data)


@frappe.whitelist()
def get_barcode_data_for_print(name):
	"""Generate eCH-0270 barcode data for a Swiss Salary Certificate.

	Module-level whitelisted function callable from Jinja print formats.
	"""
	doc = frappe.get_doc("Swiss Salary Certificate", name)
	return doc.get_barcode_data()


def _get_slips_component_totals(slip_names):
	"""Fetch aggregated component amounts from salary slips.

	Returns:
		dict mapping component names to total amounts across all slips
	"""
	if not slip_names:
		return {}

	# Get earning totals
	earnings = frappe.db.sql(
		"""
		SELECT sd.salary_component, SUM(sd.amount) as total
		FROM `tabSalary Detail` sd
		WHERE sd.parent IN %s
			AND sd.parentfield = 'earnings'
		GROUP BY sd.salary_component
		""",
		(slip_names,),
		as_dict=True,
	)

	# Get deduction totals
	deductions = frappe.db.sql(
		"""
		SELECT sd.salary_component, SUM(sd.amount) as total
		FROM `tabSalary Detail` sd
		WHERE sd.parent IN %s
			AND sd.parentfield = 'deductions'
		GROUP BY sd.salary_component
		""",
		(slip_names,),
		as_dict=True,
	)

	result = {}
	for row in earnings:
		result[row.salary_component] = flt(row.total, 2)
	for row in deductions:
		result[row.salary_component] = flt(row.total, 2)

	return result


def aggregate_salary_slips_for_lohnausweis(slips_data, position_map):
	"""Aggregate salary component totals into Lohnausweis positions.

	Pure function (no frappe dependency) for testability.

	Args:
		slips_data: dict mapping component names to total amounts
		position_map: dict mapping component names to Lohnausweis position strings

	Returns:
		dict mapping Lohnausweis position strings to aggregated amounts
	"""
	position_totals = {}

	for component, amount in slips_data.items():
		position = position_map.get(component)
		if not position:
			continue
		position_totals[position] = round(position_totals.get(position, 0) + float(amount), 2)

	return position_totals
