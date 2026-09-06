# //// Neoffice — added file (no upstream equivalent). `Swiss QST Tariff.tariff_type`
# //// stored its French label in the database ("Salaires", "Autres revenus"), which
# //// RULE #00 forbids and which a rename alone cannot fix: eleven code sites read
# //// `"SAL" if tariff_type == "Salaires" else "VSL"`, so every unrecognised value
# //// silently became "other income" — a salary tariff read against the wrong ESTV
# //// table, i.e. a wrong deduction on a real payslip.
# ////
# //// This runs in pre_model_sync, BEFORE the DocType JSON with the new Select
# //// options is synced, so the rows are migrated while the old values are still the
# //// legal ones. Inventory of 2026-09-06: 26 rows on osiris (dev), ZERO on every
# //// client instance — the migration is done at the cheapest moment of its life.
import frappe

RENAMES = {
	"Salaires": "Salary",
	"Autres revenus": "Other Income",
}


def execute():
	"""Move tariff_type from its French label to its English one, in place."""
	if not frappe.db.table_exists("Swiss QST Tariff"):
		return

	# the column can be gone (a fresh site syncs the new options first) — then
	# there is nothing stored to migrate.
	if not frappe.db.has_column("Swiss QST Tariff", "tariff_type"):
		return

	total = 0
	for old, new in RENAMES.items():
		count = frappe.db.count("Swiss QST Tariff", {"tariff_type": old})
		if not count:
			continue
		frappe.db.sql(
			"""UPDATE `tabSwiss QST Tariff` SET tariff_type = %s WHERE tariff_type = %s""",
			(new, old),
		)
		total += count
		print(f"Swiss QST Tariff: {count} row(s) {old!r} -> {new!r}")

	# Anything left is neither label: name it rather than guess. The controller now
	# refuses such a value, so it must be visible before it reaches a payslip.
	leftovers = frappe.db.sql(
		"""SELECT tariff_type, COUNT(*) FROM `tabSwiss QST Tariff`
		   WHERE tariff_type NOT IN ('Salary', 'Other Income') GROUP BY tariff_type""",
	)
	for value, count in leftovers:
		print(f"Swiss QST Tariff: {count} row(s) hold an unknown tariff_type {value!r} — left as is")

	frappe.db.commit()
	if not total and not leftovers:
		print("Swiss QST Tariff: nothing to migrate")
