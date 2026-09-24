# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

# //// Neoffice — _lt import added for COMPONENT_NAME_MESSAGES below (e4a2e4abf "fix(i18n): the Swiss payroll speaks French, payslip first")
import frappe
from frappe import _, _lt
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# //// Neoffice — cint import added for ensure_swiss_leave_types below.
from frappe.utils import cint

# //// Neoffice — removed DEFAULT_LOHNAUSWEIS_MAPPING import (bd93e5035 "feat(payroll): the Swiss salary certificate, delivered — and the onboarding asks the payroll choices"): the certificate now places each slip row by its component's own position, no default mapping to import.
from hrms.regional.switzerland.constants import (
	CROSS_BORDER_COUNTRIES,
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
	# //// Neoffice — no default certificate mapping any more (2026-09-23): the certificate places
	# //// each slip row by its component's own position; the mapping only overrides.


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
			# //// Neoffice — new field: the canton this slip's source tax was settled with. The recap per
			# //// canton read the employee's CURRENT canton, so a move mid-year sent the whole year's tax
			# //// to the new canton; the slip now keeps its own (patch set_source_tax_canton_on_salary_slips).
			{
				"fieldname": "ch_qst_canton",
				"label": "QST Canton Used",
				"fieldtype": "Data",
				"insert_after": "ch_qst_tariff_code",
				"read_only": 1,
				"no_copy": 1,
				"description": "Canton this slip was settled with — the canton its source tax is declared and paid to.",
			},
			{
				"fieldname": "ch_qst_aperiodic",
				"label": "QST Aperiodic Share",
				"fieldtype": "Currency",
				# //// Neoffice — after ch_qst_canton now (was ch_qst_tariff_code).
				"insert_after": "ch_qst_canton",
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
				# //// Neoffice — new field: the hook records the base and rate of each contribution
				# //// on the slip, so the payslip can print them and the declaration can declare them
				# //// (AVS after the pensioners' exemption, prorated AC/LAA, insured LAAC/IJM salaries)
				# //// (35e9ce9b4 "fix(payroll): Swiss 5-centime rounding, cumulated insurance ceilings, recorded bases")
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
			# //// Neoffice ▼▼▼ — new fields: Salary Slip gains an "Accounting" section (ch_accrual_entry,
			# //// ch_payment_entry) linking the journal entries that book and pay it; a booked slip is
			# //// corrected through them, not cancelled (5984103a7 "feat(payroll): book the Swiss payroll and pay it through the payment proposal")
			# The journal entries that booked this slip (accounting.py): the salary entry of the
			# period, then its payment. A booked slip is corrected through them, not cancelled.
			{
				"fieldname": "ch_accounting_section",
				"label": "Accounting",
				"fieldtype": "Section Break",
				"insert_after": "ch_contribution_bases",
				"collapsible": 1,
				"depends_on": "eval:doc.ch_accrual_entry || doc.ch_payment_entry",
			},
			{
				"fieldname": "ch_accrual_entry",
				"label": "Salary Journal Entry",
				"fieldtype": "Link",
				"options": "Journal Entry",
				"insert_after": "ch_accounting_section",
				"read_only": 1,
				"no_copy": 1,
				"allow_on_submit": 1,
				"print_hide": 1,
			},
			{
				"fieldname": "ch_payment_entry",
				"label": "Payment Journal Entry",
				"fieldtype": "Link",
				"options": "Journal Entry",
				"insert_after": "ch_accrual_entry",
				"read_only": 1,
				"no_copy": 1,
				"allow_on_submit": 1,
				"print_hide": 1,
			},
			# //// Neoffice ▲▲▲
			# //// Neoffice — new fields: when the payslip was printed from the monthly payroll page
			# //// (distribution.mark_printed), to hand out or to post with its WebStamp. An e-mail is
			# //// already traced by its Email Queue, a stamp by its WebStamp order: a print left no trace.
			{
				"fieldname": "ch_delivery_section",
				"label": "Payslip Delivery",
				"fieldtype": "Section Break",
				"insert_after": "ch_payment_entry",
				"collapsible": 1,
				"depends_on": "eval:doc.ch_printed_on",
			},
			{
				"fieldname": "ch_printed_on",
				"label": "Printed on",
				"fieldtype": "Datetime",
				"insert_after": "ch_delivery_section",
				"read_only": 1,
				"no_copy": 1,
				"allow_on_submit": 1,
				"print_hide": 1,
			},
		],
		"Salary Component Account": [
			{
				# An employer contribution is a charge AND a liability: "account" is the
				# institution's current account credited, this one the charge debited.
				"fieldname": "ch_expense_account",
				# //// Neoffice — was "Employer Charge Account": employee contributions are credited to it
				# //// too under the "Social Charges" booking method.
				"label": "Social Charge Account",
				"fieldtype": "Link",
				"options": "Account",
				"insert_after": "account",
				"in_list_view": 1,
				# //// Neoffice — employee contributions use it too since the "Social Charges" booking
				# //// method (Company.ch_payroll_booking_method): they are credited to the charge there.
				"description": (
					"The social charge account (5700-5799). An employer contribution debits it and "
					"credits the liability on the left. An employee contribution credits it instead of "
					"the liability when the company books its payroll through the social charges."
				),
			},
		],
		"Salary Component": [
			# --- Swiss Wage Type (top of form, after abbreviation) ---
			{
				"fieldname": "ch_wage_type_section",
				# //// Neoffice — label was French in the source; the French comes from the catalogue.
				"label": "Swiss Wage Type",
				"fieldtype": "Section Break",
				"insert_after": "salary_component_abbr",
			},
			{
				"fieldname": "ch_wage_type",
				# //// Neoffice — label was French in the source; the French comes from the catalogue.
				"label": "Swiss Wage Type",
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
			# //// Neoffice — the two Swissdec wage type behaviours a subject flag cannot express
			# //// (guidelines 6.0, 5.2.1 and 8.7.2): a "-" wage type that takes back from the gross
			# //// and the bases (2050, 2060), and one that raises the bases without being paid
			# //// (1920 tips, 2065 short-time work loss). See utils.sum_insurance_bases.
			{
				"fieldname": "ch_negative_wage_type",
				"label": "Negative Wage Type",
				"fieldtype": "Check",
				"insert_after": "ch_subject_to_imp",
				"default": "0",
				"depends_on": "eval:doc.type == 'Earning'",
				"description": (
					"Enter the amount as a positive number: the slip deducts it from the gross "
					"salary and from every base ticked above (e.g. 2050 correction of a daily "
					"allowance, 2060 short-time work deduction)."
				),
			},
			{
				"fieldname": "ch_bases_only",
				"label": "Counts in the Bases Only",
				"fieldtype": "Check",
				"insert_after": "ch_negative_wage_type",
				"default": "0",
				"depends_on": "eval:doc.type == 'Earning'",
				"description": (
					"Not paid and not part of the gross salary: the amount only raises the bases "
					"ticked above (e.g. 1920 tips subject to AVS, 2065 short-time work loss of "
					"earnings). Tick 'Do Not Include in Total' as well."
				),
			},
			{
				"fieldname": "ch_lohnausweis_position",
				# //// Neoffice — label was half German, half French in the source.
				"label": "Salary Certificate Position",
				"fieldtype": "Select",
				# //// Neoffice — inserted after the two checks above; 13.3 (training paid by the
				# //// employer, 2026 Wegleitung Rz 61) added to the options.
				"insert_after": "ch_bases_only",
				"options": "\n1\n2.1\n2.2\n2.3\n3\n4\n5\n6\n7\n9\n10.1\n10.2\n12\n13.1.1\n13.1.2\n13.2.1\n13.2.2\n13.2.3\n13.3\n14",
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
				# //// Neoffice — "leave empty" now derives both ends from the birth date and the
				# //// gender (Swissdec guidelines 8.1.1), see avs_exemption.resolve_avs_status.
				"description": (
					"Leave empty and the status follows from the date of birth and the gender: "
					"liable from 1 January of the year of the 18th birthday, pensioner from the "
					"month after the AVS reference age. 'youth': below the contribution start age "
					"— no AVS and no AC. 'retired': past the reference age, AVS is due only "
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
			# //// Neoffice — added 2026-09-24: how the monthly payslip reaches the employee, remembered
			# //// from one month to the next by the payroll cycle's distribution step (distribution.py).
			{
				"fieldname": "ch_payslip_delivery",
				"label": "Payslip Delivery",
				"fieldtype": "Select",
				"options": "\nEmail\nBy Post\nBy Hand",
				"insert_after": "ch_exit_date",
				"description": "Email: sent by e-mail. By Post: franked with a WebStamp and mailed. By Hand: printed and handed out. Empty: by e-mail when the employee has an address, else by hand.",
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
				# //// Neoffice — the English source carried French words; the French comes from the catalogue.
				"description": "Check if this employee is subject to withholding tax.",
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
				# //// Neoffice — the English source carried German and French words, see above.
				"description": "Check if this employee is a cross-border commuter.",
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
			# //// Neoffice ▼▼▼ — the two ways a pension fund may keep an employee's LPP insurance going
			# //// (LPP art. 33a and 33b), each an agreement between the employee and the fund, read by
			# //// utils.get_lpp_maintenance and utils.get_lpp_age.
			{
				"fieldname": "ch_lpp_section",
				"label": "Occupational Pension (LPP)",
				"fieldtype": "Section Break",
				"insert_after": "ch_ijm_code_2",
				"collapsible": 1,
			},
			{
				"fieldname": "ch_lpp_maintained_salary",
				"label": "Maintained LPP Salary (art. 33a)",
				"fieldtype": "Currency",
				"insert_after": "ch_lpp_section",
				"description": (
					"From 58, after a salary cut of half at most, the annual salary the employee keeps "
					"insured until the reference age, if the fund's regulations allow it. The extra "
					"contributions are paid by the employee unless the employer agreed to a share."
				),
			},
			{
				"fieldname": "ch_lpp_maintained_employer_share",
				"label": "Employer Share of the Maintenance (%)",
				"fieldtype": "Percent",
				"insert_after": "ch_lpp_maintained_salary",
				"depends_on": "eval:doc.ch_lpp_maintained_salary",
			},
			{
				"fieldname": "ch_lpp_column_break",
				"fieldtype": "Column Break",
				"insert_after": "ch_lpp_maintained_employer_share",
			},
			{
				"fieldname": "ch_lpp_after_reference_age",
				"label": "LPP Continued After the Reference Age (art. 33b)",
				"fieldtype": "Check",
				"insert_after": "ch_lpp_column_break",
				"default": "0",
				"description": (
					"The employee keeps working past the AVS reference age and asked the fund to stay "
					"insured: LPP contributions continue, at the latest until the age of 70."
				),
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
			# //// Neoffice — the two ways Swiss SMEs book salaries (SME chart, 4.4 and 4.5 of the usual
			# //// accounting manuals), chosen per company: accounting.accrual_lines applies it.
			{
				"fieldname": "ch_payroll_booking_method",
				"label": "Payroll Booking Method",
				"fieldtype": "Select",
				"options": "Social Insurance Liability\nSocial Charges",
				"default": "Social Insurance Liability",
				"insert_after": "ch_employer_cost_account",
				"description": (
					"Social Insurance Liability: every month the employee deductions and the employer "
					"contributions are credited to the insurers' current accounts (2270-2274) and the "
					"employer contributions charged (5700-5799); the insurers' invoices then settle "
					"those accounts. Social Charges: the employee deductions are credited straight to "
					"the charge accounts (5700-5799) and the employer contributions are not booked "
					"monthly — the insurers' invoices are charged in full when they are paid. Source "
					"tax stays a liability (2279) in both."
				),
			},
			# //// Neoffice — where the allowances the employer pays out for an insurer are debited:
			# //// with the salaries, or to a receivable the insurer's reimbursement clears.
			{
				"fieldname": "ch_third_party_allowance_booking",
				"label": "Third-Party Allowances",
				"fieldtype": "Select",
				"options": "Salaries\nInsurer Receivable",
				"default": "Salaries",
				"insert_after": "ch_payroll_booking_method",
				"description": (
					"Allowances the employer pays out for an insurer (APG, maternity, accident, sickness, "
					"AI, short-time work compensation). Salaries: debited with the salaries (5000), the "
					"insurer's reimbursement is credited back there. Insurer Receivable: debited to a "
					"receivable (1180) that the reimbursement clears, so the balance sheet shows what "
					"each insurer still owes."
				),
			},
			{
				"fieldname": "ch_third_party_allowance_account",
				"label": "Third-Party Allowances Account",
				"fieldtype": "Link",
				"options": "Account",
				"insert_after": "ch_third_party_allowance_booking",
				"depends_on": "eval:doc.ch_third_party_allowance_booking == 'Insurer Receivable'",
				"description": "Filled from the chart of accounts at the first booking when left empty.",
			},
			# //// Neoffice — where the collection commission of the source tax is credited (Swiss
			# //// insurer statements, line « Source Tax Commission »).
			{
				"fieldname": "ch_source_tax_commission_account",
				"label": "Source Tax Commission Account",
				"fieldtype": "Link",
				"options": "Account",
				"insert_after": "ch_third_party_allowance_account",
				"description": (
					"Income where the collection commission the canton leaves the employer on the source tax "
					"is credited (SME chart: Autres produits). Filled from the chart when left empty."
				),
			},
			# --- Swissdec / ELM fields ---
			{
				"fieldname": "ch_swissdec_section",
				"label": "Swissdec / ELM",
				"fieldtype": "Section Break",
				# //// Neoffice — after the payroll accounting choices, which now close the section above.
				"insert_after": "ch_source_tax_commission_account",
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


# //// Neoffice ▼▼▼ — the payslip prints each component through _(row.name), but the names this
# module creates were never extracted for translation, so a French payslip read "AVS/AI/APG
# Employee", "Source Tax Employee"; this list feeds _lt() into the catalogue while the names
# themselves stay English, since they are the document keys shared by every language
# (e4a2e4abf "fix(i18n): the Swiss payroll speaks French, payslip first")
# The payslip prints each component through _(row.name): the names this module creates are
# listed here for the translation catalogue. The names themselves stay in English — they are
# the keys of the documents, shared by every language of the fleet.
COMPONENT_NAME_MESSAGES = (
	_lt("AVS/AI/APG Employee"),
	_lt("AVS/AI/APG Employer"),
	_lt("AC/ALV Employee"),
	_lt("AC/ALV Employer"),
	_lt("LAA Professional Employer"),
	_lt("LAA Non-Professional Employee"),
	_lt("LAA Non-Professional Employer"),
	_lt("LAAC Employee"),
	_lt("LAAC Employer"),
	_lt("LPP/BVG Employee"),
	_lt("LPP/BVG Employer"),
	_lt("IJM/KTG Employee"),
	_lt("IJM/KTG Employer"),
	_lt("Family Allowances Employer"),
	# //// Neoffice — see the block marker above: AVS admin fees translation
	_lt("AVS Administrative Fees Employer"),
	_lt("Source Tax Employee"),
	_lt("13th Month Salary"),
	_lt("Overtime Pay"),
	_lt("Vacation Allowance"),
	_lt("Bonus"),
	_lt("APG Allowance"),
	_lt("IJM Sickness Allowance"),
	_lt("Maternity Allowance"),
	_lt("Child Allowance"),
	_lt("Travel Expenses"),
	_lt("Car Expenses"),
	_lt("Meal Expenses"),
	_lt("Flat-Rate Representation Expenses"),
)
# //// Neoffice ▲▲▲


def get_swiss_salary_component_definitions():
	"""Return definitions for all Swiss salary components."""
	return [
		# --- AVS/AI/APG ---
		{
			"name": "AVS/AI/APG Employee",
			"salary_component": "AVS/AI/APG Employee",
			"salary_component_abbr": "AVS_EE",
			# //// Neoffice — its salary certificate box: the certificate reads it from the component
			# //// since 2026-09-23 (the default mapping that used to place it is gone).
			"ch_lohnausweis_position": "9",
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
			# //// Neoffice — its salary certificate box: the certificate reads it from the component
			# //// since 2026-09-23 (the default mapping that used to place it is gone).
			"ch_lohnausweis_position": "9",
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
			# //// Neoffice — its salary certificate box: the certificate reads it from the component
			# //// since 2026-09-23 (the default mapping that used to place it is gone).
			"ch_lohnausweis_position": "9",
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
			# //// Neoffice — its salary certificate box: the certificate reads it from the component
			# //// since 2026-09-23 (the default mapping that used to place it is gone).
			"ch_lohnausweis_position": "10.1",
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
		# //// Neoffice — the compensation fund's administrative fees: a percentage of the AVS/AI/APG
		# //// contributions (config avs_admin_fee_rate), charged to the employer and invoiced by the
		# //// fund with the contributions. Without them the fund's current account never balanced.
		{
			"name": "AVS Administrative Fees Employer",
			"salary_component": "AVS Administrative Fees Employer",
			"salary_component_abbr": "AVS_FEE",
			"type": "Deduction",
			"description": "AVS/AI/APG compensation fund administrative fees - employer only",
			"depends_on_payment_days": 0,
			"amount_based_on_formula": 0,
			"amount": 0,
			"do_not_include_in_total": 1,
			"_is_employer": True,
		},
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
			# //// Neoffice — subject to IJM (Swissdec guidelines 6.0, 5.2.1), was 0.
			"ch_subject_to_ijm": 1,
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
			# //// Neoffice — subject to IJM (Swissdec guidelines 6.0, 5.2.1), was 0.
			"ch_subject_to_ijm": 1,
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
			# //// Neoffice — box 1 with the salary: "sämtliche Zulagen" (Wegleitung 2026 Rz 15).
			"ch_lohnausweis_position": "1",
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
			# //// Neoffice — its salary certificate box: the certificate reads it from the component
			# //// since 2026-09-23 (the default mapping that used to place it is gone).
			"ch_lohnausweis_position": "12",
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


# //// Neoffice — rewritten (2026-09-24). Upstream of this fork created ONE structure, once, for the
# //// default company, left it in draft and paid the salary through "Basic" (no Swiss wage type):
# //// a second company on the same instance had no structure to assign its employees to, the first
# //// had to submit it by hand, and the base salary reached the declarations without its wage
# //// type 1000. Now each company gets its own, submitted, when its payroll is set up.
def create_swiss_salary_structure():
	"""The default company's Swiss salary structure (setup wizard)."""
	company = frappe.defaults.get_global_default("company")
	if company and frappe.db.get_value("Company", company, "country") == "Switzerland":
		ensure_company_salary_structure(company)


# //// Neoffice — old create_swiss_salary_structure() returned early when a draft "Salary Structure" already existed for the structure name; removed together with that check (073533643 "feat(payroll): a hired employee is payable, and each company gets its Swiss salary structure"): ensure_company_salary_structure below looks up, creates and submits the structure per company instead.
# //// Neoffice — added: the Swiss absences that are not an annual quota. Sickness, accident, military
# //// or civil service, maternity and the other parent's leave are paid on by the employer (CO 324a)
# //// or compensated (IJM, LAA, APG): upstream's leave types refuse such an application for lack of
# //// an allocation (validate_balance_leaves), so "sick from the 22nd to the 26th" could not be
# //// recorded. The first is the one hrms creates at install (_("Sick Leave")).
SWISS_ABSENCE_TYPES = (
	"Sick Leave",
	"Accident",
	"Military or civil service",
	"Maternity leave",
	"Other-parent leave",
)
# //// Neoffice — leave counted in WORKING days in Switzerland: vacation (4 weeks = 20 days for a
# //// five-day week, CO 329a) and the install's casual and compensatory leave, and the other
# //// parent's two weeks (10 days, CO 329g). Upstream creates every type with include_holiday, so a
# //// fortnight off consumed 12 days, a week spanning a weekend 7 of 25. Sickness, accident,
# //// service and maternity keep the calendar count their daily allowances (IJM, LAA, APG) use.
WORKING_DAY_LEAVE_TYPES = ("Privilege Leave", "Casual Leave", "Compensatory Off", "Other-parent leave")
# Created by the hrms install under their plain translation (hrms/setup.py).
INSTALL_LEAVE_TYPES = ("Sick Leave", "Privilege Leave", "Casual Leave", "Compensatory Off")


def swiss_absence_type_name(label):
	"""The name a Swiss leave type has on this site: the install's own translation for the types
	hrms creates, the "leave type" context for ours ("Accident" alone is a word of the whole
	interface)."""
	# //// Neoffice — was `if label == "Sick Leave"`; extended to INSTALL_LEAVE_TYPES (b3c5d4138 "fix(payroll):
	# //// Swiss vacation and the other parent's leave count working days") so vacation, casual and
	# //// compensatory leave also use the install's plain translation, not the "leave type" context.
	if label in INSTALL_LEAVE_TYPES:
		return _(label)
	return _(label, context="leave type")


def ensure_swiss_leave_types():
	"""The Swiss absences, as leave types an application never lacks the balance for, and every
	leave counted the Swiss way (working or calendar days).

	An existing absence type (under its translated or its English name) gets allow_negative, a leave
	counted in working days loses include_holiday; whether a type is paid (is_lwp) stays the
	company's choice. A missing absence type is created in the site's language, paid, without
	allocation. Returns what was created and what was aligned.
	"""
	report = {"created": [], "aligned": []}
	for label in SWISS_ABSENCE_TYPES:
		name = swiss_absence_type_name(label)
		existing = next((n for n in (name, label) if frappe.db.exists("Leave Type", n)), None)
		if existing:
			if not cint(frappe.db.get_value("Leave Type", existing, "allow_negative")):
				frappe.db.set_value("Leave Type", existing, "allow_negative", 1)
				report["aligned"].append(existing)
			continue
		frappe.get_doc(
			{
				"doctype": "Leave Type",
				"leave_type_name": name,
				"allow_negative": 1,
				"is_lwp": 0,
				# //// Neoffice — was `"include_holiday": 1` (b3c5d4138 "fix(payroll): Swiss vacation and the
				# //// other parent's leave count working days"): a newly created leave type now counts
				# //// working days when it is one of WORKING_DAY_LEAVE_TYPES, calendar days otherwise.
				"include_holiday": 0 if label in WORKING_DAY_LEAVE_TYPES else 1,
				"allow_encashment": 0,
				"is_carry_forward": 0,
			}
		).insert(ignore_permissions=True)
		report["created"].append(name)
	# //// Neoffice — added (b3c5d4138 "fix(payroll): Swiss vacation and the other parent's leave count
	# //// working days"): an *existing* working-day leave type (created before this fix, or under its
	# //// English name) also loses include_holiday, so past installs get aligned, not just new ones.
	for label in WORKING_DAY_LEAVE_TYPES:
		existing = next(
			(n for n in (swiss_absence_type_name(label), label) if frappe.db.exists("Leave Type", n)), None
		)
		if existing and cint(frappe.db.get_value("Leave Type", existing, "include_holiday")):
			frappe.db.set_value("Leave Type", existing, "include_holiday", 0)
			if existing not in report["aligned"]:
				report["aligned"].append(existing)
	return report


def ensure_company_salary_structure(company):
	"""The name of ``company``'s Swiss salary structure — created, submitted and active when the
	company has none: the monthly salary (wage type 1000) as its earning, the Swiss deductions,
	whose amounts the payroll computes (update_swiss_social_contributions)."""
	existing = frappe.get_all(
		"Salary Structure",
		filters={"company": company, "docstatus": 1, "is_active": "Yes"},
		pluck="name",
		order_by="creation asc",
	)
	for name in existing:
		if frappe.db.exists(
			"Salary Detail",
			{"parent": name, "parenttype": "Salary Structure", "salary_component": "AVS/AI/APG Employee"},
		):
			return name

	name = "Swiss Payroll - Standard"
	if frappe.db.exists("Salary Structure", name):
		name = "{} - {}".format(name, frappe.get_cached_value("Company", company, "abbr"))
		if frappe.db.exists("Salary Structure", name):
			return name if frappe.db.get_value("Salary Structure", name, "docstatus") == 1 else None

	doc = frappe.new_doc("Salary Structure")
	# //// Neoffice — new: submitted Salary Structure per company (073533643 "feat(payroll): a hired employee is payable, and each company gets its Swiss salary structure"), named "Swiss Payroll - Standard" (suffixed with the company abbreviation on a name clash).
	doc.name = name
	doc.__newname = name
	doc.company = company
	doc.currency = frappe.get_cached_value("Company", company, "default_currency") or "CHF"
	doc.payroll_frequency = "Monthly"
	doc.is_active = "Yes"
	# //// Neoffice — earning is now the wage-type-1000 component (see _monthly_salary_component() below) instead of the hardcoded "Basic" component (073533643 "feat(payroll): a hired employee is payable, and each company gets its Swiss salary structure").
	doc.append(
		"earnings",
		{"salary_component": _monthly_salary_component(), "formula": "base", "amount_based_on_formula": 1},
	)
	# //// Neoffice — new: append the Swiss deductions straight from the salary-component catalogue (073533643 "feat(payroll): a hired employee is payable, and each company gets its Swiss salary structure"), skipping any component not yet created — replaces the old fixed "deductions" list appended below.
	for definition in get_swiss_salary_component_definitions():
		if definition.get("type") != "Deduction" or not frappe.db.exists(
			"Salary Component", definition["name"]
		):
			continue
		doc.append(
			"deductions",
			{
				"salary_component": definition["name"],
				"abbr": definition["salary_component_abbr"],
				"formula": definition.get("formula", ""),
				"amount_based_on_formula": definition.get("amount_based_on_formula", 0),
				"condition": definition.get("condition", ""),
				"do_not_include_in_total": definition.get("do_not_include_in_total", 0),
			},
		)
	# //// Neoffice — removed the old "for ded in deductions: doc.append("deductions", ded)" loop (073533643 "feat(payroll): a hired employee is payable, and each company gets its Swiss salary structure"): replaced by the catalogue-driven loop above.
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()
	return doc.name


# //// Neoffice — new: resolve the monthly-salary earning from wage type 1000 (creating the component from the Swiss Wage Type catalogue when missing) instead of hardcoding "Basic" (073533643 "feat(payroll): a hired employee is payable, and each company gets its Swiss salary structure").
def _monthly_salary_component():
	"""The component of the monthly salary: the one of wage type 1000, created from the catalogue
	when missing; "Basic" only where the catalogue is not installed."""
	from hrms.regional.switzerland.payroll_hooks import _resolve_component_by_wage_type

	component = _resolve_component_by_wage_type(1000, "Salaire mensuel")
	if component:
		return component
	if frappe.db.exists("Swiss Wage Type", "CH-WT-1000"):
		from hrms.regional.switzerland.api import _create_component_from_wage_type

		return _create_component_from_wage_type(frappe.get_doc("Swiss Wage Type", "CH-WT-1000"))
	return "Basic"


# //// Neoffice — removed populate_default_lohnausweis_mapping() (bd93e5035 "feat(payroll): the Swiss salary certificate, delivered — and the onboarding asks the payroll choices"): the certificate now places each slip row by its component's own position, so there is nothing left to prefill from a default mapping.
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
