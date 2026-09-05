# //// Neoffice — added file (no upstream equivalent): composite index on Swiss QST Tariff Bracket.
# //// Without it every source-tax lookup full-scans the imported ESTV brackets (457 s
# //// per query measured on 2.8M rows).
import frappe


def execute():
	"""Add the composite lookup index on Swiss QST Tariff Bracket.

	lookup_qst_rate and tariff_code_exists filter on (canton, tariff_code,
	tariff_type) then range on valid_from/income_from with ORDER BY ...
	DESC LIMIT 1. Without this index every lookup is a full table scan of
	the imported bracket rows (457s per query observed with 2.8M rows).
	"""
	if not frappe.db.table_exists("Swiss QST Tariff Bracket"):
		return
	frappe.db.add_index(
		"Swiss QST Tariff Bracket",
		["canton", "tariff_code", "tariff_type", "valid_from", "income_from"],
		index_name="idx_qst_lookup",
	)
