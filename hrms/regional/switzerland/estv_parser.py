# //// Neoffice — added file (no upstream equivalent): parser for the fixed-width ASCII source-tax
# //// tariff files published by the ESTV for the 26 cantons.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Parser for ESTV (Federal Tax Administration) source tax tariff files.

Handles the fixed-width ASCII format published by the ESTV for all 26 cantons.
Supports both salary tariffs (tar*.txt) and other income tariffs (vsl*.txt).

File format (type 06 records, 62 chars):
    [0:2]   Record type "06"
    [2:4]   Transaction type "01"
    [4:6]   Canton code (ZH, GE, etc.)
    [6:9]   Tariff code (3 chars: letter + digit + Y/N)
    [9:16]  Spacing (7 spaces)
    [16:24] Valid from (YYYYMMDD)
    [24:33] Income from in Rappen (9 digits, ÷100 = CHF)
    [33:42] Step in Rappen (9 digits, ÷100 = CHF)
    [42]    Space
    [43:45] Number of children (2 digits)
    [45:55] Tax amount in Rappen (10 digits, usually 0)
    [55:59] Tax rate in 0.01% (4 digits: 0025 = 0.25%)
    [59:62] Padding
"""

import io
import zipfile

import frappe
from datetime import date


# //// Neoffice — added helper: one place to decide what an unreadable ESTV number means. It
# //// means "unknown", which is None — never 0.0, which in this file is a real amount that the
# //// payroll would go on to withhold (or not withhold).
def _parse_rappen(raw, divisor=100.0):
	"""Fixed-width ESTV integer field -> float, or None when it cannot be read."""
	try:
		return int(raw) / divisor
	except (ValueError, TypeError):
		return None


def parse_line(line):
	"""Parse one fixed-width line from an ESTV tariff file.

	Only processes type 06 records (tariff bracket data).
	Returns None for other record types or invalid lines.

	Args:
		line: A single line string from the tariff file.

	Returns:
		dict with parsed fields, or None if not a type 06 record.
	"""
	line = line.rstrip("\n\r")

	if len(line) < 59:
		return None

	record_type = line[0:2]
	if record_type != "06":
		return None

	canton = line[4:6].strip()
	tariff_code = line[6:9].strip()
	valid_from_str = line[16:24].strip()
	income_from_rappen = line[24:33].strip()
	step_rappen = line[33:42].strip()
	num_children_str = line[43:45].strip()
	tax_amount_rappen = line[45:55].strip()
	tax_rate_hundredths = line[55:59].strip()

	# Parse valid_from date
	valid_from = None
	if valid_from_str and len(valid_from_str) == 8:
		try:
			valid_from = date(
				int(valid_from_str[0:4]),
				int(valid_from_str[4:6]),
				int(valid_from_str[6:8]),
			)
		except (ValueError, IndexError):
			pass

	# //// Neoffice — each of the five numbers below used to be wrapped in
	# //// `except (ValueError, TypeError): <field> = 0.0`. A record whose amount or rate could
	# //// not be read was therefore imported as a bracket that withholds NOTHING, and one whose
	# //// income_from could not be read was imported as a bracket starting at 0, which shadows
	# //// the real first bracket of the tariff. Both are silent: the import reports its usual
	# //// count, the table looks complete, and the employees in that income band are simply
	# //// under-withheld until somebody reconciles with the canton. A bracket we cannot read is
	# //// not a bracket worth zero — the record is dropped and counted, see parse_estv_tariff_file.
	# Convert Rappen to CHF
	income_from = _parse_rappen(income_from_rappen)
	income_step = _parse_rappen(step_rappen)

	# //// Neoffice — was `except (ValueError, TypeError): num_children = 0`, see the block at
	# //// the top of this function. Blank is a legitimate absence (a tariff with no children
	# //// dimension); anything else means the record is not what we think it is.
	if not num_children_str:
		num_children = 0
	else:
		try:
			num_children = int(num_children_str)
		except (ValueError, TypeError):
			# //// Neoffice — drop the record instead of calling it zero children.
			return None

	# Convert tax amount from Rappen to CHF
	# //// Neoffice — _parse_rappen, not a try/except that ends on 0.0. See the top of this function.
	tax_amount = _parse_rappen(tax_amount_rappen)

	# Convert tax rate from 0.01% units to decimal (e.g., 0025 → 0.0025 = 0.25%)
	# //// Neoffice — _parse_rappen, not a try/except that ends on 0.0 (a zero RATE).
	tax_rate = _parse_rappen(tax_rate_hundredths, divisor=10000.0)

	# //// Neoffice — added: any of the four unreadable means the bracket is not usable at all.
	if income_from is None or income_step is None or tax_amount is None or tax_rate is None:
		return None

	return {
		"canton": canton.upper(),
		"tariff_code": tariff_code,
		"valid_from": str(valid_from) if valid_from else None,
		"income_from": income_from,
		"income_step": income_step,
		"num_children": num_children,
		"tax_amount": tax_amount,
		"tax_rate": tax_rate,
	}


def parse_estv_tariff_file(file_content, canton=None):
	"""Parse a full ESTV tariff TXT file.

	Args:
		file_content: File content as bytes or string.
		canton: Optional canton filter. If provided, only lines matching
			this canton are included.

	Returns:
		List of dicts with bracket data.
	"""
	if isinstance(file_content, bytes):
		# ESTV files use Latin-1 encoding
		file_content = file_content.decode("latin-1")

	brackets = []
	# //// Neoffice — added: a type 06 record that parse_line refuses is a bracket of the cantonal
	# //// withholding table that we did NOT import. Dropping it silently leaves a hole in the
	# //// tariff that only shows up as an under-withheld employee months later, so say it once
	# //// per file. Non-06 records (headers, footers) are not counted: they are not brackets.
	skipped = 0
	for line in file_content.splitlines():
		parsed = parse_line(line)
		if parsed is None:
			# //// Neoffice — added: count the BRACKETS we refused, not the headers and footers.
			if line.rstrip("\n\r")[0:2] == "06":
				skipped += 1
			continue
		if canton and parsed["canton"] != canton.upper():
			continue
		brackets.append(parsed)

	# //// Neoffice — added, see the comment above the counter: one line per file, never silence.
	if skipped:
		frappe.log_error(
			"ESTV tariff: unreadable bracket records skipped",
			f"{skipped} type 06 record(s) could not be parsed and were NOT imported "
			f"(canton filter: {canton or 'none'}). The tariff table is incomplete.",
		)

	return brackets


def download_estv_tariff(year, tariff_type="SAL", canton=None):
	"""Download a tariff ZIP file from ESTV.

	Args:
		year: Full year (e.g., 2026).
		tariff_type: "SAL" for salary tariffs, "VSL" for other income.
		canton: Optional 2-letter canton code. If None, downloads the national ZIP.

	Returns:
		ZIP file content as bytes.
	"""
	import requests

	yy = str(year)[2:]

	if tariff_type == "SAL":
		base_path = "loehne"
		prefix = "tar"
	else:
		base_path = "uebrige-einkuenfte"
		prefix = "vsl"

	if canton:
		filename = f"{prefix}{yy}{canton.lower()}.zip"
	else:
		filename = f"{prefix}{year}.zip"

	url = f"https://www.estv2.admin.ch/qst/{year}/{base_path}/{filename}"

	# Canonical mirror on the fleet hub (ADR: official data comes from the
	# source, the hub keeps the canonical archive) — used when the ESTV
	# URL scheme moves or the download fails. Overridable per site.
	mirror_base = (
		frappe.conf.get("swiss_estv_mirror_url")
		or "https://neoservice.neoffice.me/files/estv"
	).rstrip("/")
	mirror_url = f"{mirror_base}/{filename}"

	try:
		response = requests.get(url, timeout=120)
		response.raise_for_status()
		return response.content
	except Exception:
		frappe.log_error(
			"ESTV download failed, trying the hub mirror",
			f"{url} failed: {frappe.get_traceback()}\nFalling back to {mirror_url}",
		)

	response = requests.get(mirror_url, timeout=120)
	response.raise_for_status()
	return response.content


def extract_txt_from_zip(zip_bytes):
	"""Extract TXT files from a ZIP archive.

	Args:
		zip_bytes: ZIP file content as bytes.

	Returns:
		dict mapping filenames to content bytes.
	"""
	result = {}

	with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
		for info in zf.infolist():
			name = info.filename.lower()
			# Handle nested ZIPs (ESTV sometimes nests canton ZIPs inside national ZIP)
			if name.endswith(".zip"):
				inner_bytes = zf.read(info.filename)
				try:
					inner_files = extract_txt_from_zip(inner_bytes)
					result.update(inner_files)
				except zipfile.BadZipFile:
					pass
			elif name.endswith(".txt"):
				result[info.filename] = zf.read(info.filename)

	return result


def bulk_import_tariff_brackets(parent_tariff_name, brackets, tariff_type):
	"""Bulk-insert bracket rows into the database.

	Uses raw SQL for performance (~800k rows across 26 cantons).

	Args:
		parent_tariff_name: Name of the parent Swiss QST Tariff record.
		brackets: List of dicts from parse_estv_tariff_file().
		tariff_type: "SAL" or "VSL".
	"""
	import frappe

	if not brackets:
		return

	batch_size = 5000
	now = frappe.utils.now_datetime()

	for i in range(0, len(brackets), batch_size):
		batch = brackets[i : i + batch_size]
		values = []
		for b in batch:
			values.append(
				(
					parent_tariff_name,
					b["canton"],
					b["tariff_code"],
					tariff_type,
					b.get("valid_from"),
					b["income_from"],
					b["income_step"],
					b["num_children"],
					b["tax_amount"],
					b["tax_rate"],
					now,
					now,
					"Administrator",
					"Administrator",
				)
			)

		placeholders = ", ".join(["(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(batch))

		frappe.db.sql(
			f"""INSERT INTO `tabSwiss QST Tariff Bracket`
			(parent_tariff, canton, tariff_code, tariff_type, valid_from,
			 income_from, income_step, num_children, tax_amount, tax_rate,
			 creation, modified, owner, modified_by)
			VALUES {placeholders}""",
			[val for row in values for val in row],
		)

	frappe.db.commit()
	ensure_bracket_lookup_index()


def ensure_bracket_lookup_index():
	"""Guarantee the composite lookup index on the bracket table.

	lookup_qst_rate / tariff_code_exists filter on (canton, tariff_code,
	tariff_type) then range on valid_from/income_from with ORDER BY ...
	DESC LIMIT 1. Without this index every lookup is a full scan of the
	~2.8M bracket rows (457s per query observed on osiris). Re-asserted
	after every bulk import because a table rebuild (reload-doc) drops it.
	"""
	import frappe

	frappe.db.add_index(
		"Swiss QST Tariff Bracket",
		["canton", "tariff_code", "tariff_type", "valid_from", "income_from"],
		index_name="idx_qst_lookup",
	)
