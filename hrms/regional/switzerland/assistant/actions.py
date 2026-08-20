import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from hrms.regional.switzerland.assistant.validators import format_avs_number, format_uid_bfs


def create_insurance_config(data):
	"""Create or update Swiss Social Insurance Config from collected data."""
	company = data.get("company")
	canton = data.get("canton", "")

	if not company:
		frappe.throw(_("Company is required"))

	# Check if config already exists
	existing = frappe.db.exists(
		"Swiss Social Insurance Config",
		{"company": company, "canton": canton},
	)

	if existing:
		doc = frappe.get_doc("Swiss Social Insurance Config", existing)
	else:
		doc = frappe.new_doc("Swiss Social Insurance Config")
		doc.company = company
		doc.canton = canton

	# Map collected data to config fields
	rate_fields = [
		"avs_rate_employee",
		"avs_rate_employer",
		"ac_rate_employee",
		"ac_rate_employer",
		"ac_annual_ceiling",
		# AC solidarity rates dropped: contribution abolished on 2023-01-01.
		"laa_professional_rate",
		"laa_nonprofessional_rate",
		"laa_insurable_salary_cap",
		"lpp_employer_share_pct",
		"lpp_entry_threshold",
		"lpp_coordination_deduction",
		"lpp_minimum_insured_salary",
		"lpp_maximum_coordinated_salary",
		"ijm_rate_employee",
		"ijm_rate_employer",
		"family_allowance_rate",
	]

	for field in rate_fields:
		if field in data and data[field] is not None:
			doc.set(field, data[field])

	# Feature toggles
	toggle_fields = ["qst_enabled", "cb_enabled", "swissdec_enabled"]
	for field in toggle_fields:
		if field in data:
			doc.set(field, 1 if data[field] else 0)

	# Thirteenth month
	if "thirteenth_month_mode" in data:
		doc.thirteenth_month_mode = data["thirteenth_month_mode"]

	# GL accounts
	account_fields = [
		"avs_employer_account",
		"ac_employer_account",
		"laa_employer_account",
		"lpp_employer_account",
		"ijm_employer_account",
		"family_allowance_account",
		"qst_gl_account",
	]
	for field in account_fields:
		if data.get(field):
			doc.set(field, data[field])

	doc.save(ignore_permissions=True)
	return doc.name


def setup_company(data):
	"""Update Company with Swiss-specific fields."""
	company = data.get("company")
	if not company:
		frappe.throw(_("Company is required"))

	updates = {}

	if data.get("uid_bfs"):
		updates["ch_uid_bfs"] = format_uid_bfs(data["uid_bfs"])

	if data.get("swiss_social_insurance_config"):
		updates["ch_swiss_social_insurance_config"] = data["swiss_social_insurance_config"]

	if data.get("swissdec_contact_person"):
		updates["ch_swissdec_contact_person"] = data["swissdec_contact_person"]

	if data.get("swissdec_contact_phone"):
		updates["ch_swissdec_contact_phone"] = data["swissdec_contact_phone"]

	if data.get("swissdec_contact_email"):
		updates["ch_swissdec_contact_email"] = data["swissdec_contact_email"]

	if updates:
		frappe.db.set_value("Company", company, updates)

	return company


def setup_employee_swiss(employee_name, data):
	"""Update Employee with Swiss-specific fields."""
	if not employee_name:
		frappe.throw(_("Employee name is required"))

	updates = {}

	# Basic Swiss fields
	field_map = {
		"avs_number": "ch_avs_number",
		"entry_date": "ch_entry_date",
		"nationality": "ch_nationality",
		"work_percentage": "ch_work_percentage",
		"permit_type": "ch_permit_type",
		"residence_country": "ch_residence_country",
		"fiscal_canton": "ch_fiscal_canton",
	}

	for src, dst in field_map.items():
		if data.get(src):
			value = data[src]
			if src == "avs_number":
				value = format_avs_number(value)
			updates[dst] = value

	# QST fields
	qst_map = {
		"qst_subject": "ch_qst_subject",
		"qst_tariff_letter": "ch_qst_tariff_letter",
		"qst_tariff_code": "ch_qst_tariff_code",
		"qst_taxation_canton": "ch_qst_taxation_canton",
		"qst_num_children": "ch_qst_num_children",
		"qst_church_tax": "ch_qst_church_tax",
	}

	for src, dst in qst_map.items():
		if src in data:
			updates[dst] = data[src]

	# Cross-border fields
	cb_map = {
		"is_cross_border": "ch_is_cross_border",
		"cross_border_start_date": "ch_cross_border_start_date",
	}

	for src, dst in cb_map.items():
		if src in data:
			updates[dst] = data[src]

	if updates:
		frappe.db.set_value("Employee", employee_name, updates)

	return employee_name


def create_salary_assignment(employee_name, base_salary, company=None):
	"""Create a Salary Structure Assignment for an employee."""
	if not employee_name or not base_salary:
		frappe.throw(_("Employee and base salary are required"))

	# Find the Swiss salary structure
	salary_structure = frappe.db.get_value(
		"Salary Structure",
		{"name": ["like", "%Swiss%"], "docstatus": 1, "company": company},
		"name",
	)

	if not salary_structure:
		salary_structure = frappe.db.get_value(
			"Salary Structure",
			{"name": ["like", "%Swiss%"], "docstatus": 1},
			"name",
		)

	if not salary_structure:
		frappe.throw(_("No submitted Swiss Salary Structure found. Please create one first."))

	# Check for existing active assignment
	existing = frappe.db.exists(
		"Salary Structure Assignment",
		{
			"employee": employee_name,
			"salary_structure": salary_structure,
			"docstatus": 1,
		},
	)

	if existing:
		return existing

	ssa = frappe.new_doc("Salary Structure Assignment")
	ssa.employee = employee_name
	ssa.salary_structure = salary_structure
	ssa.company = company or frappe.db.get_value("Employee", employee_name, "company")
	ssa.from_date = getdate(nowdate())
	ssa.base = base_salary
	ssa.save(ignore_permissions=True)
	ssa.submit()

	return ssa.name


def trigger_qst_fetch(canton, year=None):
	"""Trigger QST tariff fetch for a canton and year."""
	if not year:
		year = getdate(nowdate()).year

	try:
		from hrms.regional.switzerland.source_tax import fetch_qst_tariffs

		result = fetch_qst_tariffs(canton=canton, year=year)
		return {
			"success": True,
			"message": _("QST tariffs fetched for {0} {1}").format(canton, year),
			"count": result if isinstance(result, int) else 0,
		}
	except Exception as e:
		frappe.log_error("QST Tariff Fetch Failed", str(e))
		return {
			"success": False,
			"message": _("Failed to fetch QST tariffs: {0}").format(str(e)),
		}
