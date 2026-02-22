import frappe


def execute():
	"""Add composite index on Swiss QST Tariff Bracket for fast lookups."""
	if not frappe.db.table_exists("tabSwiss QST Tariff Bracket"):
		return

	# Check if index already exists
	indexes = frappe.db.sql(
		"SHOW INDEX FROM `tabSwiss QST Tariff Bracket` WHERE Key_name = 'idx_qst_lookup'",
		as_dict=True,
	)
	if indexes:
		return

	frappe.db.sql(
		"""ALTER TABLE `tabSwiss QST Tariff Bracket`
		ADD INDEX idx_qst_lookup (canton, tariff_code, tariff_type, valid_from, income_from)"""
	)

	# Also add index on parent_tariff for cascade deletes
	indexes = frappe.db.sql(
		"SHOW INDEX FROM `tabSwiss QST Tariff Bracket` WHERE Key_name = 'idx_parent_tariff'",
		as_dict=True,
	)
	if not indexes:
		frappe.db.sql(
			"""ALTER TABLE `tabSwiss QST Tariff Bracket`
			ADD INDEX idx_parent_tariff (parent_tariff)"""
		)
