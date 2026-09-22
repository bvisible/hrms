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


# //// Neoffice — frappe calls setup_wizard_complete hooks with the wizard's args; setup() takes none (TypeError in the wizard, CI). This wrapper takes them (7501dab6e "fix(install): the setup_wizard_complete hook receives the wizard args")
def setup_after_wizard(args=None):
	"""setup_wizard_complete hook: provision the Swiss payroll for a Swiss company only.

	frappe passes the wizard's args. The wage types, salary components and salary structure
	are Swiss by nature (like erpnext's regional setups, keyed on the company country); a
	company set up elsewhere — the test wizard creates an Indian one — must not get them.
	"""
	country = (args or {}).get("country") if isinstance(args, dict) else getattr(args, "country", None)
	if not country:
		country = frappe.db.get_value("Company", frappe.defaults.get_global_default("company"), "country")
	if country == "Switzerland":
		setup()


def setup():
	make_custom_fields()
	create_swiss_wage_types()
	create_swiss_salary_components()
	create_swiss_salary_structure()
	populate_default_lohnausweis_mapping()


def uninstall():
	custom_fields = get_custom_fields()
	delete_custom_fields(custom_fields)


def make_custom_fields(update=True):
	custom_fields = get_custom_fields()
	create_custom_fields(custom_fields, update=update)


def create_swiss_wage_types():
	"""Create all Swiss Wage Type catalog entries from the standard reference data."""
	from hrms.regional.switzerland.wage_type_data import get_swiss_wage_types

	if not frappe.db.table_exists("Swiss Wage Type"):
		return

	wage_types = get_swiss_wage_types()
	for wt in wage_types:
		name = f"CH-WT-{wt['code']}"
		if not frappe.db.exists("Swiss Wage Type", name):
			doc = frappe.new_doc("Swiss Wage Type")
			doc.update(wt)
			doc.insert(ignore_permissions=True)

	frappe.db.commit()


def get_custom_fields():
	canton_options = "\n" + "\n".join(SWISS_CANTONS)
	permit_options = "\n".join(PERMIT_TYPES)

	return {
		"Salary Slip": [
			{
				"fieldname": "ch_qst_section",
				"label": "Swiss Source Tax",
				"fieldtype": "Section Break",
				"insert_after": "total_deduction",
				"collapsible": 1,
				"depends_on": "eval:doc.ch_qst_tariff_code",
			},
			{
				"fieldname": "ch_qst_tariff_code",
				"label": "QST Tariff Code Used",
				"fieldtype": "Data",
				"insert_after": "ch_qst_section",
				"read_only": 1,
				"no_copy": 1,
				"description": "Tariff code this slip was settled with — the audit trail retroactive corrections rely on.",
			},
			{
				"fieldname": "ch_qst_aperiodic",
				"label": "QST Aperiodic Share",
				"fieldtype": "Currency",
				"insert_after": "ch_qst_tariff_code",
				"read_only": 1,
				"no_copy": 1,
				"description": "Aperiodic earnings of this slip (bonuses, lump 13th month) — excluded from the day-extrapolated determinant.",
			},
			{
				"fieldname": "ch_qst_correction_details",
				"label": "QST Retroactive Corrections",
				"fieldtype": "Small Text",
				"insert_after": "ch_qst_aperiodic",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				# Written by the payroll hook, read by the payslip: the base and rate each
				# contribution was computed with (capped salary, business-unit or code rate).
				"fieldname": "ch_contribution_bases",
				"label": "Contribution Bases",
				"fieldtype": "JSON",
				"insert_after": "ch_qst_correction_details",
				"read_only": 1,
				"hidden": 1,
				"no_copy": 1,
				"print_hide": 1,
			},
		],
		"Salary Component": [
			# --- Swiss Wage Type (top of form, after abbreviation) ---
			{
				"fieldname": "ch_wage_type_section",
				"label": "Type de salaire suisse",
				"fieldtype": "Section Break",
				"insert_after": "salary_component_abbr",
			},
			{
				"fieldname": "ch_wage_type",
				"label": "Type de salaire suisse",
				"fieldtype": "Link",
				"options": "Swiss Wage Type",
				"insert_after": "ch_wage_type_section",
				# //// Neoffice — description translated from French; a patch migrates the existing Custom
				# //// Field rows, filtered on the exact old value (b62d7bdeb "fix(swiss-payroll): the tariff type, the field labels and the payslip wording leave French behind")
				"description": "Select a standard wage type to fill in the insurance bases and the Lohnausweis position automatically.",
				"fetch_from": "",
			},
			{
				"fieldname": "ch_wage_type_code",
				"label": "Code",
				"fieldtype": "Data",
				"insert_after": "ch_wage_type",
				"read_only": 1,
				"fetch_from": "ch_wage_type.code",
				"translatable": 0,
			},
			# --- Swiss Employer Contribution ---
			{
				"fieldname": "ch_employer_section",
				# //// Neoffice — see above: label translated from French
				"label": "Employer / Employee Share",
				"fieldtype": "Section Break",
				"insert_after": "ch_wage_type_code",
				"depends_on": "eval:doc.type == 'Deduction'",
			},
			{
				"fieldname": "is_employer_contribution",
				# //// Neoffice — see above: label translated from French
				"label": "Employer Share",
				"fieldtype": "Check",
				"insert_after": "ch_employer_section",
				"default": "0",
				# //// Neoffice — see above: description translated from French
				"description": "When ticked, this component is the employer's share and is hidden from the payslip.",
			},
			{
				"fieldname": "linked_component",
				# //// Neoffice — see above: label translated from French
				"label": "Linked Component (Employee/Employer)",
				"fieldtype": "Link",
				"options": "Salary Component",
				"insert_after": "is_employer_contribution",
				# //// Neoffice — see above: description translated from French
				"description": "Link to the paired component (employee or employer) of this social charge.",
			},
			# --- Swiss Social Insurance Bases ---
			{
				"fieldname": "ch_insurance_base_section",
				# //// Neoffice — see above: label translated from French
				"label": "Swiss Social Insurance Bases",
				"fieldtype": "Section Break",
				"insert_after": "linked_component",
			},
			{
				"fieldname": "ch_subject_to_avs",
				# //// Neoffice — see above: label translated from French
				"label": "Subject to AVS",
				"fieldtype": "Check",
				"insert_after": "ch_insurance_base_section",
				"default": "1",
			},
			{
				"fieldname": "ch_subject_to_ac",
				# //// Neoffice — see above: label translated from French
				"label": "Subject to AC",
				"fieldtype": "Check",
				"insert_after": "ch_subject_to_avs",
				"default": "1",
			},
			{
				"fieldname": "ch_subject_to_laa",
				# //// Neoffice — see above: label translated from French
				"label": "Subject to LAA",
				"fieldtype": "Check",
				"insert_after": "ch_subject_to_ac",
				"default": "1",
			},
			{
				"fieldname": "ch_column_break_insurance",
				"fieldtype": "Column Break",
				"insert_after": "ch_subject_to_laa",
			},
			{
				"fieldname": "ch_subject_to_ijm",
				# //// Neoffice — see above: label translated from French
				"label": "Subject to IJM",
				"fieldtype": "Check",
				"insert_after": "ch_column_break_insurance",
				"default": "1",
			},
			{
				"fieldname": "ch_subject_to_lpp",
				# //// Neoffice — see above: label translated from French
				"label": "Subject to LPP",
				"fieldtype": "Check",
				"insert_after": "ch_subject_to_ijm",
				"default": "1",
			},
			{
				"fieldname": "ch_subject_to_imp",
				# //// Neoffice — see above: label translated from French
				"label": "Subject to Withholding Tax",
				"fieldtype": "Check",
				"insert_after": "ch_subject_to_lpp",
				"default": "1",
				# //// Neoffice — see above: description translated from French
				"description": "When ticked, this component counts towards the withholding-tax base.",
			},
			{
				"fieldname": "ch_lohnausweis_position",
				"label": "Position Lohnausweis",
				"fieldtype": "Select",
				"insert_after": "ch_subject_to_imp",
				"options": "\n1\n2.1\n2.2\n2.3\n3\n4\n5\n6\n7\n9\n10.1\n10.2\n12\n13.1.1\n13.1.2\n13.2.1\n13.2.2\n13.2.3\n14",
				"translatable": 0,
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
			# //// Neoffice — added ch_avs_status (declared status, Swissdec wording, not inferred
			# from birth date) so AVS/AC liability accounts for apprentices below contribution
			# start age and employees past reference age (1a3e1cc45 "feat(payroll): Swiss AVS
			# liability by age and status")
			{
				"fieldname": "ch_avs_status",
				"label": "AVS Status",
				"fieldtype": "Select",
				# Swissdec wording, so the value exports as-is and can be diffed
				# against a certified payroll. Blank = ordinary full liability.
				"options": "\nyouth\nexempted\nretired\nretired_waive_exemption",
				"insert_after": "ch_fiscal_canton",
				"translatable": 0,
				"description": (
					"Leave empty for the ordinary case. 'youth': below the contribution start age "
					"(18) — no AVS and no AC. 'retired': past the reference age, AVS is due only "
					"above CHF 1'400/month and no AC is due. 'retired_waive_exemption': past the "
					"reference age but the employee waived the exemption (AVS 21) to earn a higher "
					"pension — full AVS, still no AC."
				),
			},
			# //// Neoffice — added ch_qst_predefined_category (Swissdec CategoryPredefinedType)
			# so a person liable to source tax but holding no tariff code — HEN/HEY, MEN/MEY,
			# NON/NOY, or SFN under the French special agreement — can still be declared
			# (be078717a "fix(payroll): emit TaxAtSourceCategory, not a bare TariffCode")
			{
				"fieldname": "ch_qst_predefined_category",
				"label": "Source Tax Predefined Category",
				"fieldtype": "Select",
				# Swissdec CategoryPredefinedType (Common.xsd). Replaces the tariff
				# code for someone liable to source tax who has none.
				"options": "\nHEN\nHEY\nMEN\nMEY\nNON\nNOY\nSFN",
				"insert_after": "ch_avs_status",
				"translatable": 0,
				"description": (
					"Leave empty in the ordinary case — the tariff code is then used. "
					"HEN/HEY: board fee of a non-resident (linear rate). MEN/MEY: employee "
					"participation realised after leaving Switzerland. NON/NOY: period during "
					"which the person was not liable, for a correction. SFN: French special "
					"agreement — set automatically for a French resident in BL, BS, SO, VD, VS, "
					"NE, JU or BE holding the 2041-AS attestation; nothing is withheld but the "
					"salary is still declared."
				),
			},
			{
				"fieldname": "ch_column_break",
				"fieldtype": "Column Break",
				# //// Neoffice — the column break follows the two Swiss status fields added
				# //// on 2026-09-22 (ch_avs_status, then ch_qst_predefined_category), so the
				# //// left column carries permit, canton and both statuses.
				"insert_after": "ch_qst_predefined_category",
			},
			{
				"fieldname": "ch_avs_number",
				"label": "AVS Number",
				"fieldtype": "Data",
				"insert_after": "ch_column_break",
				"description": "Swiss social security number (756.XXXX.XXXX.XX)",
				"translatable": 0,
			},
			{
				"fieldname": "ch_nationality",
				"label": "Nationality",
				"fieldtype": "Link",
				"options": "Country",
				"insert_after": "ch_avs_number",
				"description": "Employee nationality (for Swissdec ELM declarations).",
			},
			{
				"fieldname": "ch_work_percentage",
				"label": "Work Percentage",
				"fieldtype": "Percent",
				"insert_after": "ch_nationality",
				"default": "100",
				"description": "Employment percentage (e.g., 80 for 80%). Used for Swissdec ELM.",
			},
			{
				"fieldname": "ch_entry_date",
				"label": "Entry Date (Swiss)",
				"fieldtype": "Date",
				"insert_after": "ch_work_percentage",
				"description": "Start of employment for Swissdec ELM reporting.",
			},
			{
				"fieldname": "ch_exit_date",
				"label": "Exit Date (Swiss)",
				"fieldtype": "Date",
				"insert_after": "ch_entry_date",
				"description": "End of employment for Swissdec ELM reporting.",
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
				"fieldname": "ch_qst_code_effective_from",
				"label": "Tariff Code Effective From",
				"fieldtype": "Date",
				"insert_after": "ch_qst_church_tax",
				"depends_on": "eval:doc.ch_qst_subject",
				"description": "Set when the tariff situation changes retroactively (marriage, birth reported late): submitted slips from this date on are re-settled on the next payroll run.",
			},
			{
				"fieldname": "ch_qst_column_break",
				"fieldtype": "Column Break",
				"insert_after": "ch_qst_code_effective_from",
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
				"description": "Auto-set: Italian frontalier who started on or after July 17, 2023. Uses the R-V tariffs (80% reduction built into the tariff files).",
			},
			{
				"fieldname": "ch_german_flat_tax",
				"label": "German Capped Tax (max 4.5%)",
				"fieldtype": "Check",
				"insert_after": "ch_is_italian_new_frontalier",
				"read_only": 1,
				"depends_on": "eval:doc.ch_is_cross_border && doc.ch_residence_country == 'DE'",
				"description": "Auto-set: German cross-border worker — withholding capped at 4.5% of gross (DTA CH-DE art. 15a, L-P tariffs). Requires the Gre-1 attestation.",
			},
			{
				"fieldname": "ch_de_gre1_attestation",
				"label": "Gre-1 Residence Attestation",
				"fieldtype": "Check",
				"insert_after": "ch_german_flat_tax",
				"depends_on": "eval:doc.ch_is_cross_border && doc.ch_residence_country == 'DE'",
				"description": "German residence attestation Gre-1/Gre-2 on file. Without it, the ordinary (uncapped) tariff applies.",
			},
			{
				"fieldname": "ch_fr_2041as_attestation",
				"label": "2041-AS Residence Attestation",
				"fieldtype": "Check",
				"insert_after": "ch_de_gre1_attestation",
				"depends_on": "eval:doc.ch_is_cross_border && doc.ch_residence_country == 'FR'",
				"description": "French residence attestation 2041-AS on file (required before January 1st). Without it, the employer must withhold at the ordinary tariff.",
			},
			{
				"fieldname": "ch_permit_expiry_date",
				"label": "Permit Expiry Date",
				"fieldtype": "Date",
				"insert_after": "ch_fr_2041as_attestation",
				"depends_on": "eval:doc.ch_is_cross_border",
			},
			# //// Neoffice ▼▼▼ — per-employee LAA/LAAC/IJM insurance codes (business unit + scope for LAA,
			# person group + category for LAAC/IJM, per Swissdec guidelines 7.4.2/7.6.1/7.7), replacing the
			# flat per-company rate (a33896d9f "feat(payroll): LAA / LAAC / IJM per insurance solution, LAA cap, Sex as M/F")
			{
				"fieldname": "ch_insurance_codes_section",
				"label": "Insurance Codes (LAA / LAAC / IJM)",
				"fieldtype": "Section Break",
				"insert_after": "ch_permit_expiry_date",
				"collapsible": 1,
				"description": (
					"The codes the insurers assigned. Leave empty when the company has a single "
					"flat rate per insurance. They are declared as-is to Swissdec."
				),
			},
			{
				"fieldname": "ch_laa_code",
				"label": "LAA Code",
				"fieldtype": "Data",
				"length": 2,
				"insert_after": "ch_insurance_codes_section",
				"description": (
					"Business unit letter + scope, e.g. A1. Scope: 0 not insured, 1 with the "
					"non-occupational premium deducted, 2 insured but the employer pays it, "
					"3 occupational only (under 8 hours a week). Chosen, never derived from the "
					"activity rate (Swissdec guidelines 7.4.2)."
				),
			},
			{
				"fieldname": "ch_insurance_codes_column_break",
				"fieldtype": "Column Break",
				"insert_after": "ch_laa_code",
			},
			{
				"fieldname": "ch_laac_code",
				"label": "LAAC Code",
				"fieldtype": "Data",
				"length": 2,
				"insert_after": "ch_insurance_codes_column_break",
				"description": "Person group + category, e.g. A1. Category 0 means not insured.",
			},
			{
				"fieldname": "ch_laac_code_2",
				"label": "LAAC Code 2",
				"fieldtype": "Data",
				"length": 2,
				"insert_after": "ch_laac_code",
				"description": "A second LAAC code, typically for the salary above the LAA ceiling.",
			},
			{
				"fieldname": "ch_insurance_codes_column_break_2",
				"fieldtype": "Column Break",
				"insert_after": "ch_laac_code_2",
			},
			{
				"fieldname": "ch_ijm_code",
				"label": "IJM Code",
				"fieldtype": "Data",
				"length": 2,
				"insert_after": "ch_insurance_codes_column_break_2",
				"description": "Person group + category, e.g. A1. Category 0 means not insured.",
			},
			{
				"fieldname": "ch_ijm_code_2",
				"label": "IJM Code 2",
				"fieldtype": "Data",
				"length": 2,
				"insert_after": "ch_ijm_code",
			},
			# //// Neoffice ▲▲▲
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
			# --- Swissdec / ELM fields ---
			{
				"fieldname": "ch_swissdec_section",
				"label": "Swissdec / ELM",
				"fieldtype": "Section Break",
				"insert_after": "ch_employer_cost_account",
				"collapsible": 1,
			},
			{
				"fieldname": "ch_uid_bfs",
				"label": "UID-BFS Number",
				"fieldtype": "Data",
				"insert_after": "ch_swissdec_section",
				"description": "Company identification number (CHE-XXX.XXX.XXX) for Swissdec ELM.",
				"translatable": 0,
			},
			{
				"fieldname": "ch_contact_person",
				"label": "Swissdec Contact Person",
				"fieldtype": "Data",
				"insert_after": "ch_uid_bfs",
				"description": "Contact person name for ELM declarations.",
			},
			{
				"fieldname": "ch_sd_column_break",
				"fieldtype": "Column Break",
				"insert_after": "ch_contact_person",
			},
			{
				"fieldname": "ch_contact_phone",
				"label": "Contact Phone",
				"fieldtype": "Data",
				"insert_after": "ch_sd_column_break",
				"description": "Phone number for ELM declarations.",
			},
			{
				"fieldname": "ch_contact_email",
				"label": "Contact Email",
				"fieldtype": "Data",
				"options": "Email",
				"insert_after": "ch_contact_phone",
				"description": "Email address for ELM declarations.",
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


def ensure_swiss_salary_components():
	"""Create, on an already-provisioned Swiss site, the salary components added since.

	//// Neoffice — added. create_swiss_salary_components() runs once, when the setup
	//// wizard completes, and never again. A component added to the definitions
	//// later never reached an existing site: the LAAC pair (2026-09-22) was absent
	//// from production, and the first slip with a LAAC rate would have died on a
	//// missing Salary Component. Wired in after_migrate, like make_custom_fields.

	Only acts where the Swiss payroll was provisioned, and only on what is missing —
	a component a client has edited is never touched, and a site with nothing
	missing pays one existence check per definition.
	"""
	if not frappe.db.exists("Salary Component", "AVS/AI/APG Employee"):
		return  # not a Swiss payroll site

	missing = [
		definition
		for definition in get_swiss_salary_component_definitions()
		if not frappe.db.exists("Salary Component", definition["name"])
	]
	if not missing:
		return

	for definition in missing:
		doc = frappe.new_doc("Salary Component")
		doc.update({k: v for k, v in definition.items() if not k.startswith("_")})
		doc.insert(ignore_permissions=True)

	# Pair only the new ones: _link_paired_components writes with set_value, which
	# would otherwise bump the modified date of every Swiss component on every migrate.
	_link_paired_components(missing)
	frappe.db.commit()


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
		# NOTE: the "AC Solidarity" components are no longer created — the
		# solidarity contribution above the AC ceiling was abolished on
		# 2023-01-01 (SECO 2022-10-13). Existing installs are cleaned up by
		# patch v15_0.remove_ac_solidarity_and_fix_ijm_mapping.
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
		# --- LAA non-occupational premium paid by the employer (LAA code scope 2) ---
		# //// Neoffice — added. With LAA scope 2 the employee is insured for
		# //// non-occupational accidents but nothing is deducted: the employer pays the
		# //// premium. It is an employer cost, not a benefit to declare — the ESTV guide
		# //// excludes employer UVG premiums (BUV and NBUV) from the salary certificate.
		{
			"name": "LAA Non-Professional Employer",
			"salary_component": "LAA Non-Professional Employer",
			"salary_component_abbr": "LAA_NP_ER",
			"type": "Deduction",
			"description": "LAA/UVG non-occupational premium paid by the employer (LAA code scope 2)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 0,
			"amount": 0,
			"do_not_include_in_total": 1,
			"_is_employer": True,
			"_linked_to": "LAA Non-Professional Employee",
		},
		# //// Neoffice — LAAC (UVGZ) was in the wage type catalogue but never had a salary
		# //// Neoffice — component, config rate, aggregation or declaration: deductions existed
		# //// Neoffice — with nothing declared for them (d0d329a43 "feat(payroll): declare LAAC (UVGZ), which was computed and declared nowhere")
		# --- LAAC/UVGZ Complementary Accident Insurance ---
		{
			"name": "LAAC Employee",
			"salary_component": "LAAC Employee",
			"salary_component_abbr": "LAAC_EE",
			"type": "Deduction",
			"description": "LAAC/UVGZ Complementary Accident Insurance - Employee share (rate set by insurer)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 0,
			"amount": 0,
			"do_not_include_in_total": 0,
		},
		{
			"name": "LAAC Employer",
			"salary_component": "LAAC Employer",
			"salary_component_abbr": "LAAC_ER",
			"type": "Deduction",
			"description": "LAAC/UVGZ Complementary Accident Insurance - Employer share (rate set by insurer)",
			"depends_on_payment_days": 1,
			"amount_based_on_formula": 0,
			"amount": 0,
			"do_not_include_in_total": 1,
			"_is_employer": True,
			"_linked_to": "LAAC Employee",
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
			# //// Neoffice — was 1181, one of our own variants. The Swissdec guidelines use
			# //// 1200 for the 13th month, so that is the code an ELM declaration must carry.
			# //// Migrated on existing sites by patches/v15_0/switzerland_13th_month_code_1200.
			"ch_wage_type": "CH-WT-1200",
			"ch_wage_type_code": "1200",
			"ch_subject_to_avs": 1,
			"ch_subject_to_ac": 1,
			"ch_subject_to_laa": 1,
			"ch_subject_to_ijm": 1,
			"ch_subject_to_lpp": 1,
			"ch_subject_to_imp": 1,
			"ch_lohnausweis_position": "1",
		},
		# --- Common Swiss Earnings ---
		{
			"name": "Overtime Pay",
			"salary_component": "Overtime Pay",
			"salary_component_abbr": "OTP",
			"type": "Earning",
			"description": "Overtime pay (Heures supplémentaires) — Code 1060",
			"depends_on_payment_days": 1,
			"remove_if_zero_valued": 1,
			"ch_wage_type": "CH-WT-1060",
			"ch_wage_type_code": "1060",
			"ch_subject_to_avs": 1,
			"ch_subject_to_ac": 1,
			"ch_subject_to_laa": 1,
			"ch_subject_to_ijm": 1,
			"ch_subject_to_lpp": 1,
			"ch_subject_to_imp": 1,
			"ch_lohnausweis_position": "1",
		},
		{
			"name": "Vacation Allowance",
			"salary_component": "Vacation Allowance",
			"salary_component_abbr": "VACA",
			"type": "Earning",
			"description": "Vacation allowance (Indemnité de vacances) — Code 1160",
			"depends_on_payment_days": 1,
			"remove_if_zero_valued": 1,
			"ch_wage_type": "CH-WT-1160",
			"ch_wage_type_code": "1160",
			"ch_subject_to_avs": 1,
			"ch_subject_to_ac": 1,
			"ch_subject_to_laa": 1,
			"ch_subject_to_ijm": 1,
			"ch_subject_to_lpp": 1,
			"ch_subject_to_imp": 1,
			"ch_lohnausweis_position": "1",
		},
		{
			"name": "Bonus",
			"salary_component": "Bonus",
			"salary_component_abbr": "BONUS",
			"type": "Earning",
			"description": "Bonus / Gratification — Code 1210",
			"depends_on_payment_days": 0,
			"remove_if_zero_valued": 1,
			"ch_wage_type": "CH-WT-1210",
			"ch_wage_type_code": "1210",
			"ch_subject_to_avs": 1,
			"ch_subject_to_ac": 1,
			"ch_subject_to_laa": 1,
			"ch_subject_to_ijm": 1,
			"ch_subject_to_lpp": 1,
			"ch_subject_to_imp": 1,
			"ch_lohnausweis_position": "3",
		},
		{
			"name": "APG Allowance",
			"salary_component": "APG Allowance",
			"salary_component_abbr": "CHAP",
			"type": "Earning",
			"description": "APG income replacement allowance (Indemnité APG) — Code 2000",
			"depends_on_payment_days": 0,
			"remove_if_zero_valued": 1,
			"ch_wage_type": "CH-WT-2000",
			"ch_wage_type_code": "2000",
			"ch_subject_to_avs": 1,
			"ch_subject_to_ac": 1,
			"ch_subject_to_laa": 0,
			"ch_subject_to_ijm": 0,
			"ch_subject_to_lpp": 0,
			"ch_subject_to_imp": 1,
			"ch_lohnausweis_position": "7",
		},
		{
			"name": "IJM Sickness Allowance",
			"salary_component": "IJM Sickness Allowance",
			"salary_component_abbr": "IIJM",
			"type": "Earning",
			"description": "Daily sickness allowance (Indemnité maladie IJM) — Code 2035",
			"depends_on_payment_days": 0,
			"remove_if_zero_valued": 1,
			"ch_wage_type": "CH-WT-2035",
			"ch_wage_type_code": "2035",
			"ch_subject_to_avs": 0,
			"ch_subject_to_ac": 0,
			"ch_subject_to_laa": 0,
			"ch_subject_to_ijm": 0,
			"ch_subject_to_lpp": 0,
			"ch_subject_to_imp": 1,
			"ch_lohnausweis_position": "7",
		},
		{
			"name": "Maternity Allowance",
			"salary_component": "Maternity Allowance",
			"salary_component_abbr": "MATA",
			"type": "Earning",
			"description": "Maternity allowance (Indemnité maternité) — Code 2040",
			"depends_on_payment_days": 0,
			"remove_if_zero_valued": 1,
			"ch_wage_type": "CH-WT-2040",
			"ch_wage_type_code": "2040",
			"ch_subject_to_avs": 1,
			"ch_subject_to_ac": 1,
			"ch_subject_to_laa": 0,
			"ch_subject_to_ijm": 0,
			"ch_subject_to_lpp": 0,
			"ch_subject_to_imp": 1,
			"ch_lohnausweis_position": "7",
		},
		{
			"name": "Child Allowance",
			"salary_component": "Child Allowance",
			"salary_component_abbr": "CHALL",
			"type": "Earning",
			"description": "Child allowance (Allocation pour enfant) — Code 3000",
			"depends_on_payment_days": 0,
			"remove_if_zero_valued": 1,
			"ch_wage_type": "CH-WT-3000",
			"ch_wage_type_code": "3000",
			"ch_subject_to_avs": 0,
			"ch_subject_to_ac": 0,
			"ch_subject_to_laa": 0,
			"ch_subject_to_ijm": 0,
			"ch_subject_to_lpp": 0,
			"ch_subject_to_imp": 0,
			"ch_lohnausweis_position": "7",
		},
		{
			"name": "Travel Expenses",
			"salary_component": "Travel Expenses",
			"salary_component_abbr": "TVLE",
			"type": "Earning",
			"description": "Travel expense reimbursement (Frais de voyage) — Code 6000",
			"depends_on_payment_days": 0,
			"remove_if_zero_valued": 1,
			"ch_wage_type": "CH-WT-6000",
			"ch_wage_type_code": "6000",
			"ch_subject_to_avs": 0,
			"ch_subject_to_ac": 0,
			"ch_subject_to_laa": 0,
			"ch_subject_to_ijm": 0,
			"ch_subject_to_lpp": 0,
			"ch_subject_to_imp": 0,
			"ch_lohnausweis_position": "13.1.1",
		},
		{
			"name": "Car Expenses",
			"salary_component": "Car Expenses",
			"salary_component_abbr": "CARE",
			"type": "Earning",
			"description": "Car expense reimbursement (Frais de voiture) — Code 6001",
			"depends_on_payment_days": 0,
			"remove_if_zero_valued": 1,
			"ch_wage_type": "CH-WT-6001",
			"ch_wage_type_code": "6001",
			"ch_subject_to_avs": 0,
			"ch_subject_to_ac": 0,
			"ch_subject_to_laa": 0,
			"ch_subject_to_ijm": 0,
			"ch_subject_to_lpp": 0,
			"ch_subject_to_imp": 0,
			"ch_lohnausweis_position": "13.1.1",
		},
		{
			"name": "Meal Expenses",
			"salary_component": "Meal Expenses",
			"salary_component_abbr": "MEAL",
			"type": "Earning",
			"description": "Meal expense reimbursement (Frais de repas) — Code 6002",
			"depends_on_payment_days": 0,
			"remove_if_zero_valued": 1,
			"ch_wage_type": "CH-WT-6002",
			"ch_wage_type_code": "6002",
			"ch_subject_to_avs": 0,
			"ch_subject_to_ac": 0,
			"ch_subject_to_laa": 0,
			"ch_subject_to_ijm": 0,
			"ch_subject_to_lpp": 0,
			"ch_subject_to_imp": 0,
			"ch_lohnausweis_position": "13.1.1",
		},
		{
			"name": "Flat-Rate Representation Expenses",
			"salary_component": "Flat-Rate Representation Expenses",
			"salary_component_abbr": "REPR",
			"type": "Earning",
			"description": "Flat-rate representation expenses (Frais forfaitaires de représentation) — Code 6040",
			"depends_on_payment_days": 0,
			"remove_if_zero_valued": 1,
			"ch_wage_type": "CH-WT-6040",
			"ch_wage_type_code": "6040",
			"ch_subject_to_avs": 0,
			"ch_subject_to_ac": 0,
			"ch_subject_to_laa": 0,
			"ch_subject_to_ijm": 0,
			"ch_subject_to_lpp": 0,
			"ch_subject_to_imp": 0,
			"ch_lohnausweis_position": "13.2.1",
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


def ensure_swiss_workspace_hierarchy():
	"""after_migrate hook: keep the Swiss Payroll workspace and sidebar order.

	The workspace sync at the end of migrate skips records edited in the
	DB and can undo what a patch set earlier in the run, so the
	hierarchy is (re)asserted after everything else. Idempotent.
	"""
	from hrms.patches.v15_0.add_swiss_payroll_workspace import execute

	try:
		execute()
	except Exception:
		frappe.log_error("Swiss workspace hierarchy hook failed", frappe.get_traceback())
