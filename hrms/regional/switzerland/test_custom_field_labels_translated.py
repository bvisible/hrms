# //// Neoffice — added file (no upstream equivalent)
# Copyright (c) 2026, Neoffice and contributors
# For license information, please see license.txt

"""The custom fields of the Swiss payroll speak French (maintenance#1615, 15.10.2026).

`regional/switzerland/setup.py` creates about ninety custom fields (`ch_*`) on Company, Employee, Salary Component and
Salary Slip, with English labels, helps and options. Frappe translates a field's text by the text itself, from the
files of every app: when none has it, the customer reads « Swiss Payroll Settings » in a French screen. 129 strings
were in that case on 15.10.

This test walks the definitions the setup creates and asks, for each label, help and word-option, that some French
file of the stack (frappe, erpnext, hrms) has it. A code (B, C, 1, HEN...) is not a word and is left alone.

A plain unittest: it reads the setup's definitions and the PO files, and needs no site.
"""

import csv
import os
import unittest
from pathlib import Path

from babel.messages.pofile import read_po

import frappe

from hrms.regional.switzerland.setup import get_custom_fields


def _po_entries(path):
	"""(msgid, msgstr) of a PO file, without its header. Babel comes with Frappe; polib is not installed on the CI's
	site, where importing it killed the whole run at collection."""
	with open(path, "rb") as handle:
		return [(m.id, m.string) for m in read_po(handle) if m.id and isinstance(m.id, str)]


def _french():
	"""text -> French over the files of the stack (frappe, erpnext, hrms: .po and the older .csv).

	The hrms .po can be swapped with NEOFFICE_HRMS_FR_PO to run this against another version of the file."""
	merged = {}
	for app in ("frappe", "erpnext", "hrms"):
		for row in _csv_rows(Path(frappe.get_app_path(app, "translations", "fr.csv"))):
			merged[row[0]] = row[1]
	po_files = [
		Path(frappe.get_app_path("frappe", "locale", "fr.po")),
		Path(frappe.get_app_path("erpnext", "locale", "fr.po")),
		Path(os.environ.get("NEOFFICE_HRMS_FR_PO") or frappe.get_app_path("hrms", "locale", "fr.po")),
	]
	for path in po_files:
		if not path.is_file():
			continue
		for msgid, msgstr in _po_entries(path):
			if msgstr:
				merged[msgid] = msgstr
	return merged


def _csv_rows(path):
	if not path.is_file():
		return []
	with path.open(encoding="utf-8", newline="") as handle:
		return [row for row in csv.reader(handle) if len(row) >= 2 and row[0] and row[1]]


def _is_word(text):
	"""A text a person reads: not empty, not a code (B, C, 1, HEN, LI)."""
	text = (text or "").strip()
	return len(text) > 3 and not text.isdigit()


def _strings():
	seen = {}
	for doctype, fields in get_custom_fields().items():
		for field in fields:
			for key in ("label", "description"):
				if _is_word(field.get(key)):
					seen.setdefault(field[key], f"{doctype}.{field['fieldname']}.{key}")
			if field.get("fieldtype") == "Select":
				for option in (field.get("options") or "").split("\n"):
					if _is_word(option):
						seen.setdefault(option, f"{doctype}.{field['fieldname']}.option")
	return seen


class TestCustomFieldLabelsTranslated(unittest.TestCase):
	def test_every_text_a_person_reads_has_a_french(self):
		french = _french()
		missing = sorted(f"{where}: {text[:70]}" for text, where in _strings().items() if text not in french)
		self.assertEqual(missing, [], f"{len(missing)} text(s) of the Swiss payroll fields have no French")


if __name__ == "__main__":
	unittest.main()
