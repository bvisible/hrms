#//// Neoffice — added file (no upstream equivalent): legal-compliance cleanup of the Swiss module.
#//// The AC solidarity contribution was abolished on 2023-01-01 and the IJM retention
#//// does not belong in position 9 of the salary certificate; existing sites are fixed
#//// in place, historical slips left untouched.
"""Legal-compliance cleanup for the Swiss payroll module (review of 2026-08-20).

1. The AC solidarity contribution (1% above the AC ceiling) was abolished on
   2023-01-01 (SECO communication of 2022-10-13; AHV/AVS leaflet 2.08) — the
   module kept withholding 0.5% + 0.5% above CHF 148'200. Disable the two
   components and drop them from salary structures.
2. The employee IJM/KTG retention does not belong in position 9 of the salary
   certificate (guide 605.040.18.1f margin no. 42, CSI FAQ 9.1) — drop that
   mapping row from existing Swiss Social Insurance Configs.
3. Create the new cross-border attestation fields (Gre-1 for Germany,
   2041-AS for France) on Employee for existing installs.

Historical salary slips are left untouched.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

SOLIDARITY_COMPONENTS = ("AC Solidarity Employee", "AC Solidarity Employer")


def execute():
	if not frappe.db.exists("DocType", "Swiss Social Insurance Config"):
		# Swiss module not installed on this site
		return

	_disable_solidarity_components()
	_remove_solidarity_from_structures()
	_fix_lohnausweis_mappings()
	_create_attestation_fields()
	frappe.clear_cache()


def _disable_solidarity_components():
	for name in SOLIDARITY_COMPONENTS:
		if frappe.db.exists("Salary Component", name):
			frappe.db.set_value(
				"Salary Component",
				name,
				{
					"disabled": 1,
					"description": (
						"OBSOLETE — the AC solidarity contribution was abolished on "
						"2023-01-01 (SECO 2022-10-13). Kept disabled because historical "
						"salary slips reference it."
					),
				},
				update_modified=False,
			)


def _remove_solidarity_from_structures():
	# Remove the rows from salary STRUCTURES only (never from slips, which
	# are historical documents). Child rows of submitted structures cannot be
	# edited via the ORM, hence the direct delete.
	frappe.db.delete(
		"Salary Detail",
		{
			"parenttype": "Salary Structure",
			"salary_component": ("in", list(SOLIDARITY_COMPONENTS)),
		},
	)


def _fix_lohnausweis_mappings():
	if not frappe.db.table_exists("Swiss Lohnausweis Mapping"):
		return
	# Employee IJM retention must not be aggregated into certificate pos. 9.
	frappe.db.delete(
		"Swiss Lohnausweis Mapping",
		{
			"salary_component": "IJM/KTG Employee",
			"lohnausweis_position": "9",
		},
	)
	# Abolished component: drop any mapping rows referencing it.
	frappe.db.delete(
		"Swiss Lohnausweis Mapping",
		{"salary_component": ("in", list(SOLIDARITY_COMPONENTS))},
	)


def _create_attestation_fields():
	if not frappe.db.exists("Custom Field", {"dt": "Employee", "fieldname": "ch_is_cross_border"}):
		# Cross-border custom fields never set up on this site.
		return
	create_custom_fields(
		{
			"Employee": [
				{
					"fieldname": "ch_de_gre1_attestation",
					"label": "Gre-1 Residence Attestation",
					"fieldtype": "Check",
					"insert_after": "ch_german_flat_tax",
					"depends_on": "eval:doc.ch_is_cross_border && doc.ch_residence_country == 'DE'",
					"description": (
						"German residence attestation Gre-1/Gre-2 on file. Without it, "
						"the ordinary (uncapped) tariff applies."
					),
				},
				{
					"fieldname": "ch_fr_2041as_attestation",
					"label": "2041-AS Residence Attestation",
					"fieldtype": "Check",
					"insert_after": "ch_de_gre1_attestation",
					"depends_on": "eval:doc.ch_is_cross_border && doc.ch_residence_country == 'FR'",
					"description": (
						"French residence attestation 2041-AS on file (required before "
						"January 1st). Without it, the employer must withhold at the "
						"ordinary tariff."
					),
				},
			]
		},
		ignore_validate=True,
	)
