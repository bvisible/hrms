# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from hrms.regional.switzerland.constants import (
	CROSS_BORDER_COUNTRIES,
	DEFAULT_LOHNAUSWEIS_MAPPING,
	PERMIT_TYPES,
	QST_TARIFF_LETTERS,
	SWISS_CANTONS,
)
from hrms.setup import delete_custom_fields


def setup():
	make_custom_fields()
	create_swiss_salary_components()
	create_swiss_salary_structure()
	populate_default_lohnausweis_mapping()


def uninstall():
	custom_fields = get_custom_fields()
	delete_custom_fields(custom_fields)


def make_custom_fields(update=True):
	custom_fields = get_custom_fields()
	create_custom_fields(custom_fields, update=update)


def get_custom_fields():
	canton_options = "\n" + "\n".join(SWISS_CANTONS)
	permit_options = "\n".join(PERMIT_TYPES)

	return {
		"Salary Component": [
			{
				"fieldname": "ch_employer_section",
				"label": "Swiss Employer Contribution",
				"fieldtype": "Section Break",
				"insert_after": "description",
				"collapsible": 1,
				"depends_on": "eval:doc.type == 'Deduction'",
			},
			{
				"fieldname": "is_employer_contribution",
				"label": "Is Employer Contribution",
				"fieldtype": "Check",
				"insert_after": "ch_employer_section",
				"default": "0",
				"description": "If checked, this component represents the employer's share and will be hidden from the employee pay slip.",
			},
			{
				"fieldname": "linked_component",
				"label": "Linked Employee/Employer Component",
				"fieldtype": "Link",
				"options": "Salary Component",
				"insert_after": "is_employer_contribution",
				"description": "Link to the paired employee or employer component for this social charge.",
			},
		],
		"Employee": [
			{
				"fieldname": "ch_swiss_payroll_section",
				"label": "Swiss Payroll",
				"fieldtype": "Section Break",
				"insert_after": "payroll_cost_center",
				"collapsible": 1,
			},
			{
				"fieldname": "ch_permit_type",
				"label": "Permit Type",
				"fieldtype": "Select",
				"options": permit_options,
				"insert_after": "ch_swiss_payroll_section",
				"translatable": 0,
			},
			{
				"fieldname": "ch_fiscal_canton",
				"label": "Fiscal Canton",
				"fieldtype": "Select",
				"options": canton_options,
				"insert_after": "ch_permit_type",
				"translatable": 0,
			},
			{
				"fieldname": "ch_column_break",
				"fieldtype": "Column Break",
				"insert_after": "ch_fiscal_canton",
			},
			{
				"fieldname": "ch_avs_number",
				"label": "AVS Number",
				"fieldtype": "Data",
				"insert_after": "ch_column_break",
				"description": "Swiss social security number (756.XXXX.XXXX.XX)",
				"translatable": 0,
			},
			# --- Source Tax (Quellensteuer) fields ---
			{
				"fieldname": "ch_qst_section",
				"label": "Source Tax (Quellensteuer)",
				"fieldtype": "Section Break",
				"insert_after": "ch_avs_number",
				"collapsible": 1,
			},
			{
				"fieldname": "ch_qst_subject",
				"label": "Subject to Source Tax",
				"fieldtype": "Check",
				"insert_after": "ch_qst_section",
				"default": "0",
				"description": "Check if this employee is subject to withholding tax (impôt à la source).",
			},
			{
				"fieldname": "ch_qst_tariff_letter",
				"label": "Tariff Category",
				"fieldtype": "Select",
				"options": "\n" + "\n".join(QST_TARIFF_LETTERS),
				"insert_after": "ch_qst_subject",
				"depends_on": "eval:doc.ch_qst_subject",
				"translatable": 0,
			},
			{
				"fieldname": "ch_qst_num_children",
				"label": "Children (Tax)",
				"fieldtype": "Int",
				"insert_after": "ch_qst_tariff_letter",
				"depends_on": "eval:doc.ch_qst_subject",
				"default": "0",
			},
			{
				"fieldname": "ch_qst_church_tax",
				"label": "Church Tax Member",
				"fieldtype": "Check",
				"insert_after": "ch_qst_num_children",
				"depends_on": "eval:doc.ch_qst_subject",
				"default": "0",
			},
			{
				"fieldname": "ch_qst_column_break",
				"fieldtype": "Column Break",
				"insert_after": "ch_qst_church_tax",
			},
			{
				"fieldname": "ch_qst_tariff_code",
				"label": "Tariff Code",
				"fieldtype": "Data",
				"insert_after": "ch_qst_column_break",
				"read_only": 1,
				"depends_on": "eval:doc.ch_qst_subject",
				"description": "Auto-composed: letter + children + church (e.g., B2Y).",
				"translatable": 0,
			},
			{
				"fieldname": "ch_qst_taxation_canton",
				"label": "Canton of Taxation",
				"fieldtype": "Select",
				"options": "\n" + "\n".join(SWISS_CANTONS),
				"insert_after": "ch_qst_tariff_code",
				"depends_on": "eval:doc.ch_qst_subject",
				"translatable": 0,
			},
			{
				"fieldname": "ch_qst_120k_flag",
				"label": "Exceeds CHF 120k",
				"fieldtype": "Check",
				"insert_after": "ch_qst_taxation_canton",
				"read_only": 1,
				"depends_on": "eval:doc.ch_qst_subject",
				"description": "Set automatically when projected annual income exceeds the ordinary taxation threshold.",
			},
			# --- Cross-Border Worker fields ---
			{
				"fieldname": "ch_cb_section",
				"label": "Cross-Border Worker",
				"fieldtype": "Section Break",
				"insert_after": "ch_qst_120k_flag",
				"collapsible": 1,
			},
			{
				"fieldname": "ch_is_cross_border",
				"label": "Cross-Border Worker",
				"fieldtype": "Check",
				"insert_after": "ch_cb_section",
				"default": "0",
				"description": "Check if this employee is a cross-border commuter (Grenzgänger/frontalier).",
			},
			{
				"fieldname": "ch_residence_country",
				"label": "Country of Residence",
				"fieldtype": "Select",
				"options": "\n" + "\n".join(CROSS_BORDER_COUNTRIES),
				"insert_after": "ch_is_cross_border",
				"depends_on": "eval:doc.ch_is_cross_border",
				"translatable": 0,
			},
			{
				"fieldname": "ch_cross_border_start_date",
				"label": "Cross-Border Start Date",
				"fieldtype": "Date",
				"insert_after": "ch_residence_country",
				"depends_on": "eval:doc.ch_is_cross_border",
				"description": "Date when cross-border status began. Used for Italian old/new frontalier determination.",
			},
			{
				"fieldname": "ch_cb_column_break",
				"fieldtype": "Column Break",
				"insert_after": "ch_cross_border_start_date",
			},
			{
				"fieldname": "ch_is_italian_new_frontalier",
				"label": "New Frontalier (post-2023)",
				"fieldtype": "Check",
				"insert_after": "ch_cb_column_break",
				"read_only": 1,
				"depends_on": "eval:doc.ch_is_cross_border && doc.ch_residence_country == 'IT'",
				"description": "Auto-set: Italian frontalier who started on or after July 17, 2023. Subject to 80% rate.",
			},
			{
				"fieldname": "ch_german_flat_tax",
				"label": "German Flat Tax (4.5%)",
				"fieldtype": "Check",
				"insert_after": "ch_is_italian_new_frontalier",
				"read_only": 1,
				"depends_on": "eval:doc.ch_is_cross_border && doc.ch_residence_country == 'DE'",
				"description": "Auto-set: German cross-border worker subject to 4.5% flat withholding tax.",
			},
			{
				"fieldname": "ch_permit_expiry_date",
				"label": "Permit Expiry Date",
				"fieldtype": "Date",
				"insert_after": "ch_german_flat_tax",
				"depends_on": "eval:doc.ch_is_cross_border",
			},
		],
		"Company": [
			{
				"fieldname": "ch_swiss_payroll_section",
				"label": "Swiss Payroll Settings",
				"fieldtype": "Section Break",
				"insert_after": "default_payroll_payable_account",
				"collapsible": 1,
			},
			{
				"fieldname": "ch_default_social_insurance_config",
				"label": "Default Swiss Social Insurance Config",
				"fieldtype": "Link",
				"options": "Swiss Social Insurance Config",
				"insert_after": "ch_swiss_payroll_section",
				"description": "Default social insurance configuration for this company.",
			},
			{
				"fieldname": "ch_employer_cost_account",
				"label": "Default Employer Social Cost Account",
				"fieldtype": "Link",
				"options": "Account",
				"insert_after": "ch_default_social_insurance_config",
				"description": "Default GL account for employer social contributions.",
			},
		],
	}


def create_swiss_salary_components():
	"""Create all Swiss social charge salary components (employee + employer pairs)."""
	components = get_swiss_salary_component_definitions()

	for comp_def in components:
		if not frappe.db.exists("Salary Component", comp_def["name"]):
			doc = frappe.new_doc("Salary Component")
			doc.update(comp_def)
			doc.insert(ignore_permissions=True)
			frappe.db.commit()

	# Link paired components
	_link_paired_components(components)


def get_swiss_salary_component_definitions():
	"""Return definitions for all Swiss salary components."""
	return [
		# --- AVS/AI/APG ---
		{
			"name": "AVS/AI/APG Employee",
			"salary_component": "AVS/AI/APG Employee",
			"salary_component_abbr": "AVS_EE",
			"type": "Deduction",
			"description": "AVS/AI/APG - Employee share (5.3%)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 1,
			"formula": "base * 0.053",
			"do_not_include_in_total": 0,
		},
		{
			"name": "AVS/AI/APG Employer",
			"salary_component": "AVS/AI/APG Employer",
			"salary_component_abbr": "AVS_ER",
			"type": "Deduction",
			"description": "AVS/AI/APG - Employer share (5.3%)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 1,
			"formula": "base * 0.053",
			"do_not_include_in_total": 1,
			"_is_employer": True,
			"_linked_to": "AVS/AI/APG Employee",
		},
		# --- AC/ALV ---
		{
			"name": "AC/ALV Employee",
			"salary_component": "AC/ALV Employee",
			"salary_component_abbr": "AC_EE",
			"type": "Deduction",
			"description": "AC/ALV Unemployment - Employee share (1.1%, ceiling CHF 148'200/year)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 1,
			"formula": "base * 0.011",
			"do_not_include_in_total": 0,
		},
		{
			"name": "AC/ALV Employer",
			"salary_component": "AC/ALV Employer",
			"salary_component_abbr": "AC_ER",
			"type": "Deduction",
			"description": "AC/ALV Unemployment - Employer share (1.1%, ceiling CHF 148'200/year)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 1,
			"formula": "base * 0.011",
			"do_not_include_in_total": 1,
			"_is_employer": True,
			"_linked_to": "AC/ALV Employee",
		},
		# --- AC Solidarity ---
		{
			"name": "AC Solidarity Employee",
			"salary_component": "AC Solidarity Employee",
			"salary_component_abbr": "ACSOL_EE",
			"type": "Deduction",
			"description": "AC Solidarity - Employee share (0.5%, only on salary above CHF 148'200/year)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 1,
			"formula": "base * 0.005",
			"condition": "0",
			"do_not_include_in_total": 0,
		},
		{
			"name": "AC Solidarity Employer",
			"salary_component": "AC Solidarity Employer",
			"salary_component_abbr": "ACSOL_ER",
			"type": "Deduction",
			"description": "AC Solidarity - Employer share (0.5%, only on salary above CHF 148'200/year)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 1,
			"formula": "base * 0.005",
			"condition": "0",
			"do_not_include_in_total": 1,
			"_is_employer": True,
			"_linked_to": "AC Solidarity Employee",
		},
		# --- LAA Professional (Employer only) ---
		{
			"name": "LAA Professional Employer",
			"salary_component": "LAA Professional Employer",
			"salary_component_abbr": "LAAP_ER",
			"type": "Deduction",
			"description": "LAA Professional Accident Insurance - Employer only (rate set by insurer)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 0,
			"amount": 0,
			"do_not_include_in_total": 1,
			"_is_employer": True,
		},
		# --- LAA Non-Professional (Employee only) ---
		{
			"name": "LAA Non-Professional Employee",
			"salary_component": "LAA Non-Professional Employee",
			"salary_component_abbr": "LAANP_EE",
			"type": "Deduction",
			"description": "LAA Non-Professional Accident Insurance - Employee only (rate set by insurer)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 0,
			"amount": 0,
			"do_not_include_in_total": 0,
		},
		# --- LPP/BVG ---
		{
			"name": "LPP/BVG Employee",
			"salary_component": "LPP/BVG Employee",
			"salary_component_abbr": "LPP_EE",
			"type": "Deduction",
			"description": "LPP/BVG Occupational Pension - Employee share (rate depends on age)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 0,
			"amount": 0,
			"do_not_include_in_total": 0,
		},
		{
			"name": "LPP/BVG Employer",
			"salary_component": "LPP/BVG Employer",
			"salary_component_abbr": "LPP_ER",
			"type": "Deduction",
			"description": "LPP/BVG Occupational Pension - Employer share (min. 50%, rate depends on age)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 0,
			"amount": 0,
			"do_not_include_in_total": 1,
			"_is_employer": True,
			"_linked_to": "LPP/BVG Employee",
		},
		# --- IJM/KTG ---
		{
			"name": "IJM/KTG Employee",
			"salary_component": "IJM/KTG Employee",
			"salary_component_abbr": "IJM_EE",
			"type": "Deduction",
			"description": "IJM/KTG Daily Sickness Allowance - Employee share (rate set by insurer)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 0,
			"amount": 0,
			"do_not_include_in_total": 0,
		},
		{
			"name": "IJM/KTG Employer",
			"salary_component": "IJM/KTG Employer",
			"salary_component_abbr": "IJM_ER",
			"type": "Deduction",
			"description": "IJM/KTG Daily Sickness Allowance - Employer share (rate set by insurer)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 0,
			"amount": 0,
			"do_not_include_in_total": 1,
			"_is_employer": True,
			"_linked_to": "IJM/KTG Employee",
		},
		# --- Family Allowances (Employer only) ---
		{
			"name": "Family Allowances Employer",
			"salary_component": "Family Allowances Employer",
			"salary_component_abbr": "FALLOC_ER",
			"type": "Deduction",
			"description": "Family Allowances - Employer only (rate varies by canton)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 0,
			"amount": 0,
			"do_not_include_in_total": 1,
			"_is_employer": True,
		},
		# --- 13th Month Salary (Earning) ---
		{
			"name": "13th Month Salary",
			"salary_component": "13th Month Salary",
			"salary_component_abbr": "13M",
			"type": "Earning",
			"description": "13th month salary (Treizième salaire) — calculated automatically by the Swiss payroll hook",
			"depends_on_payment_days": 0,
			"amount_based_on_formula": 0,
			"amount": 0,
			"do_not_include_in_total": 0,
		},
		# --- Source Tax (Quellensteuer) ---
		{
			"name": "Source Tax Employee",
			"salary_component": "Source Tax Employee",
			"salary_component_abbr": "QST",
			"type": "Deduction",
			"description": "Source tax (Quellensteuer / Impôt à la source) — calculated automatically from ESTV tariff brackets",
			"depends_on_payment_days": 0,
			"amount_based_on_formula": 0,
			"amount": 0,
			"do_not_include_in_total": 0,
		},
	]


def _link_paired_components(components):
	"""Set the is_employer_contribution flag and linked_component for employer components."""
	for comp_def in components:
		comp_name = comp_def["name"]
		is_employer = comp_def.pop("_is_employer", False)
		linked_to = comp_def.pop("_linked_to", None)

		if is_employer and frappe.db.exists("Salary Component", comp_name):
			frappe.db.set_value(
				"Salary Component",
				comp_name,
				"is_employer_contribution",
				1,
			)
			if linked_to and frappe.db.exists("Salary Component", linked_to):
				frappe.db.set_value(
					"Salary Component",
					comp_name,
					"linked_component",
					linked_to,
				)
				# Also set reverse link on the employee component
				frappe.db.set_value(
					"Salary Component",
					linked_to,
					"linked_component",
					comp_name,
				)

	frappe.db.commit()


def create_swiss_salary_structure():
	"""Create a default Salary Structure template for Swiss payroll."""
	structure_name = "Swiss Payroll - Standard"

	if frappe.db.exists("Salary Structure", structure_name):
		return

	component_defs = get_swiss_salary_component_definitions()
	deductions = []
	for comp_def in component_defs:
		if comp_def.get("type") != "Deduction":
			continue
		deductions.append(
			{
				"salary_component": comp_def["name"],
				"abbr": comp_def["salary_component_abbr"],
				"formula": comp_def.get("formula", ""),
				"amount_based_on_formula": comp_def.get("amount_based_on_formula", 0),
				"condition": comp_def.get("condition", ""),
				"do_not_include_in_total": comp_def.get("do_not_include_in_total", 0),
			}
		)

	doc = frappe.new_doc("Salary Structure")
	doc.name = structure_name
	doc.salary_structure = structure_name
	doc.payroll_frequency = "Monthly"
	doc.is_active = "Yes"

	# Add a Basic earning component as placeholder
	doc.append(
		"earnings",
		{
			"salary_component": "Basic",
			"formula": "base",
			"amount_based_on_formula": 1,
		},
	)

	for ded in deductions:
		doc.append("deductions", ded)

	doc.insert(ignore_permissions=True)
	frappe.db.commit()


def populate_default_lohnausweis_mapping():
	"""Populate Lohnausweis mapping on all existing Swiss Social Insurance Config records.

	Skips configs that already have mapping rows.
	"""
	configs = frappe.get_all("Swiss Social Insurance Config", pluck="name")
	for config_name in configs:
		config = frappe.get_doc("Swiss Social Insurance Config", config_name)
		if config.get("lohnausweis_mapping"):
			continue

		for mapping in DEFAULT_LOHNAUSWEIS_MAPPING:
			if frappe.db.exists("Salary Component", mapping["salary_component"]):
				config.append(
					"lohnausweis_mapping",
					{
						"salary_component": mapping["salary_component"],
						"lohnausweis_position": mapping["lohnausweis_position"],
						"include_in_certificate": 1,
					},
				)

		if config.get("lohnausweis_mapping"):
			config.save(ignore_permissions=True)

	frappe.db.commit()
