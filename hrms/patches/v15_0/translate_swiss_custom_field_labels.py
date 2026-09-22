# //// Neoffice — added file (no upstream equivalent). The Swiss payroll Custom Fields
# //// shipped their labels and descriptions as bare French strings, so a German- or
# //// English-speaking instance saw French — next to the English labels the same file
# //// already shipped, i.e. two languages in one form. A label is stored ON the Custom
# //// Field record, so fixing the fixture is not enough: the existing rows carry the
# //// French. The English text is now the msgid, and `locale/fr.po` carries the French.
import frappe

# fieldname -> (old French, new English) for label and description
LABELS = {
	"ch_employer_section": ("Part employeur / employé", "Employer / Employee Share"),
	"is_employer_contribution": ("Part employeur", "Employer Share"),
	"linked_component": ("Composante liée (employé/employeur)", "Linked Component (Employee/Employer)"),
	"ch_insurance_base_section": ("Bases d'assurance sociale suisse", "Swiss Social Insurance Bases"),
	"ch_subject_to_avs": ("Soumis à l'AVS", "Subject to AVS"),
	"ch_subject_to_ac": ("Soumis à l'AC", "Subject to AC"),
	"ch_subject_to_laa": ("Soumis à la LAA", "Subject to LAA"),
	"ch_subject_to_ijm": ("Soumis à l'IJM", "Subject to IJM"),
	"ch_subject_to_lpp": ("Soumis à la LPP", "Subject to LPP"),
	"ch_subject_to_imp": ("Soumis à l'impôt à la source", "Subject to Withholding Tax"),
}

DESCRIPTIONS = {
	"ch_wage_type": (
		"Sélectionner un type de salaire standard pour remplir automatiquement les bases "
		"d'assurance et la position Lohnausweis.",
		"Select a standard wage type to fill in the insurance bases and the Lohnausweis "
		"position automatically.",
	),
	"is_employer_contribution": (
		"Si coché, cette composante représente la part employeur et sera masquée du bulletin de salaire.",
		"When ticked, this component is the employer's share and is hidden from the payslip.",
	),
	"linked_component": (
		"Lien vers la composante appariée (employé ou employeur) pour cette charge sociale.",
		"Link to the paired component (employee or employer) of this social charge.",
	),
	"ch_subject_to_imp": (
		"Si coché, cette composante est incluse dans la base de l'impôt à la source.",
		"When ticked, this component counts towards the withholding-tax base.",
	),
}


def execute():
	"""Move the persisted labels and descriptions to English, only where still French.

	Idempotent by construction: each update is filtered on the exact old value, so a
	label an administrator has since reworded is never overwritten.
	"""
	changed = 0
	for field, mapping in (("label", LABELS), ("description", DESCRIPTIONS)):
		for fieldname, (old, new) in mapping.items():
			rows = frappe.get_all(
				"Custom Field", filters={"fieldname": fieldname, field: old}, pluck="name"
			)
			for name in rows:
				frappe.db.set_value("Custom Field", name, field, new, update_modified=False)
				changed += 1

	if changed:
		frappe.db.commit()
		frappe.clear_cache()
	print(f"Swiss payroll Custom Fields: {changed} label(s)/description(s) moved to English")
