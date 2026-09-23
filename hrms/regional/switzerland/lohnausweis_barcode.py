# //// Neoffice — added file (no upstream equivalent): the salary certificate 2D barcode (Swissdec
# //// annex 5: TxAB XML, deflate, PDF417).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Swissdec 2D barcode generation for Swiss Salary Certificates (Form 11).

Implements the official barcode of the salary certificate as specified by
the Swissdec guidelines, annex 5 ("Richtlinien Barcode"), for ELM 6.0
(release 20260306; the control header is unchanged since 20200220):

    Certificate data
      → TxAB XML  (root <T>, namespace
         urn:ch:swissdec:elm:v6:20260306:SalaryDeclarationTxAB)
      → Info-ZIP archive with a single entry named "txab"
      → split into symbols, each prefixed by a 14-byte control header
      → PDF417 (error correction level 2, 15 columns) → PNG

What 6.0 changed in the XML (SalaryDeclarationTxAB.xsd 20260306): <S> needs the
addresseeIDRef of the tax authority ("#TAX", as TaxSalary in the ELM declaration)
and a CreationDate after its DocID; the expense regulation approved by a canton is
ChargesRule; box 15 remarks of the official catalogue (StandardRemarks.xml) are
StandardRemark elements, and only the other ones go to <Remark> as free text
(annex 5, 3.3). Lengths follow the official stylesheet (TaxAccountingBcdTrans.xsl):
company name 30, last name 30, first name 15, ZIP 6.

14-byte control header (annex 5, chapter 2.2):
    bytes 1-4   random identification, identical for all symbols of one file
    byte  5     compression type: 'z' (Info-ZIP — only defined value)
    bytes 6-8   size of this symbol's data (header included), big-endian
    byte  9     1 for the first symbol, 2 for all following ones
    byte  10    control-character version (3 since release 20200220)
    bytes 11-12 symbol number, tens and units (values 0..9)
    bytes 13-14 total number of symbols, tens and units (values 0..9)

NOTE: eCH-0270 is the standard of the electronic TAX STATEMENT
(E-Steuerauszug), not of the salary certificate — the previous revision of
this module wrongly generated an ad-hoc XML under an eCH-0270 label.

This module has no Frappe dependency; all functions are pure Python for
maximum testability. External libraries (pdf417gen, python-barcode) are
imported lazily inside function bodies.
"""

import base64
import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile

# Swissdec TxAB (ELM 6.0) namespace
TXAB_NS = "urn:ch:swissdec:elm:v6:20260306:SalaryDeclarationTxAB"
_NS = f"{{{TXAB_NS}}}"
# SID = the vendor SystemID assigned and published by Swissdec during
# certification (max 3 chars). "0" marks an unassigned system — replace it
# via certificate_data["system_id"] once Neoffice holds a Swissdec SystemID.
DEFAULT_SYSTEM_ID = "0"
DEFAULT_SYSTEM_VERSION = "6.0"  # max 3 chars

# The salary certificate's addressee: the tax authority, as TaxSalary refers to it in the
# ELM declaration (samples of annex 5: <TaxSalary addresseeIDRef="#TAX">).
ADDRESSEE_ID_REF = "#TAX"
# Lengths of the official stylesheet (TaxAccountingBcdTrans.xsl) and of the 6.0 schema.
MAX_COMPANY_NAME, MAX_LASTNAME, MAX_FIRSTNAME, MAX_ZIP = 30, 30, 15, 6

# ZIP entry name mandated by annex 5 ("txab — tax accounting barcode")
ZIP_ENTRY_NAME = "txab"

# 14-byte control header constants (annex 5, chapter 2.2)
HEADER_SIZE = 14
COMPRESSION_ZIP = 0x7A  # ASCII 'z' — Info-ZIP, the only defined compression
CONTROL_VERSION = 3  # always 3 since release 20200220

# PDF417 parameters per annex 5 (chapter 2.3-2.4: EC level 2; the reference
# implementation uses 15 columns)
PDF417_COLUMNS = 15
PDF417_SECURITY_LEVEL = 2
PDF417_SCALE = 3
PDF417_RATIO = 3
PDF417_PADDING = 20

# Maximum ZIP payload bytes per symbol. Annex 5 (3.1): "generally all the data fit in one
# barcode", at most 1000 bytes; the second one goes on an additional page. The first prints in
# box H of the form (250 x 120 px). 15 columns fill its width (module 0.196 mm); in Byte
# compaction (pdf417_code_words) 850 + 14 header bytes make 49 rows, which still fit its
# height at that width, so the module does not shrink. Real certificates zip to 710-800
# bytes: one symbol, one page (550 put every one of them on two pages). Bigger files are
# split across symbols that the scanner reassembles via the control header (max 99).
MAX_PAYLOAD_PER_SYMBOL = 850

# All Form 11 position IDs handled by the print/DocType layer
POSITION_IDS = [
	"1", "2.1", "2.2", "2.3", "3", "4", "5", "6", "7",
	"8", "9", "10.1", "10.2", "11", "12",
	"13.1.1", "13.1.2", "13.2.1", "13.2.2", "13.2.3", "13.3",
	"14", "15",
]  # fmt: skip

# Register default namespace so output uses xmlns= on root, not ns0: prefix
ET.register_namespace("", TXAB_NS)


# ---------------------------------------------------------------------------
# TxAB XML generation
# ---------------------------------------------------------------------------
def generate_txab_xml(certificate_data):
	"""Generate the Swissdec TxAB XML document for a salary certificate.

	Args:
		certificate_data: dict with keys:
			- employer: dict (name, address, uid_bfs, zip_code, city)
			- employee: dict (name, avs_number, date_of_birth,
			  date_of_joining, relieving_date)
			- fiscal_year: str (e.g. "2025")
			- posting_date: str (ISO date)
			- positions: dict mapping position IDs to values
			  (float for 1-14, str for 15)
			- free_transport / lunch_checks: optional booleans (boxes F/G)
			- descriptions: optional dict mapping position IDs ("2.3", "3",
			  "4", "7", "13.1.2", "13.2.3", "14") to their text
			- certificate_id: optional str (document name → DocID/SID)

	Returns:
		bytes: UTF-8 encoded XML
	"""
	employer = certificate_data.get("employer", {})
	employee = certificate_data.get("employee", {})
	positions = certificate_data.get("positions", {})
	descriptions = certificate_data.get("descriptions", {}) or {}
	fiscal_year = str(certificate_data.get("fiscal_year", ""))
	doc_id = str(certificate_data.get("certificate_id") or "") or _fallback_doc_id(
		employer.get("uid_bfs", ""), employee.get("avs_number", ""), fiscal_year
	)

	root = ET.Element(f"{_NS}T")
	root.set("SID", str(certificate_data.get("system_id") or DEFAULT_SYSTEM_ID)[:3])
	root.set("SysV", str(certificate_data.get("system_version") or DEFAULT_SYSTEM_VERSION)[:3])

	# --- Company (attribute-based per CompanyIDType) ---
	comp = ET.SubElement(root, f"{_NS}Company")
	uid = _format_uid(employer.get("uid_bfs", ""))
	if uid:
		comp.set("UID-BFS", uid)
	comp.set("HR-RC-Name", _limit(employer.get("name"), MAX_COMPANY_NAME) or "-")
	comp.set("ZIP", _limit(employer.get("zip_code"), MAX_ZIP) or "-")
	# Box I: who answers for the certificate (the stylesheet's ContactPerson / ContactPhone).
	if certificate_data.get("contact_person"):
		comp.set("Person", _limit(certificate_data["contact_person"]))
	if certificate_data.get("contact_phone"):
		comp.set("Phone", _limit(certificate_data["contact_phone"]))
	street = _extract_street(employer.get("address", ""))
	if street:
		comp.set("Street", street)
	if employer.get("city"):
		comp.set("City", employer["city"])

	# --- PersonID: identity attributes + choice SV-AS-Nr | DateOfBirth | unknown ---
	person = ET.SubElement(root, f"{_NS}PersonID")
	first_name, last_name = _split_person_name(employee)
	person.set("Lastname", _limit(last_name, MAX_LASTNAME) or "-")
	person.set("Firstname", _limit(first_name, MAX_FIRSTNAME) or "-")
	person.set("ZIP", _limit(employee.get("zip_code"), MAX_ZIP) or "-")
	person.set("City", employee.get("city", "") or "-")
	if employee.get("street"):
		person.set("Street", employee["street"])
	avs = _format_avs(employee.get("avs_number", ""))
	if avs:
		ET.SubElement(person, f"{_NS}SV-AS-Nr").text = avs
	elif employee.get("date_of_birth"):
		ET.SubElement(person, f"{_NS}DateOfBirth").text = employee["date_of_birth"]
	else:
		ET.SubElement(person, f"{_NS}unknown")

	# --- S = salary certificate (TaxSalaryType) ---
	s = ET.SubElement(root, f"{_NS}S")
	s.set("addresseeIDRef", ADDRESSEE_ID_REF)
	ET.SubElement(s, f"{_NS}DocID").text = doc_id
	ET.SubElement(s, f"{_NS}CreationDate").text = _creation_date(certificate_data.get("creation_date"))

	period = ET.SubElement(s, f"{_NS}Period")
	date_from, date_until = _certificate_period(
		fiscal_year, employee.get("date_of_joining", ""), employee.get("relieving_date", "")
	)
	ET.SubElement(period, f"{_NS}from").text = date_from
	ET.SubElement(period, f"{_NS}until").text = date_until

	if certificate_data.get("free_transport"):
		ET.SubElement(s, f"{_NS}FreeTransport")
	if certificate_data.get("lunch_checks"):
		ET.SubElement(s, f"{_NS}CanteenLunchCheck")

	def amount(pos_id):
		return round(float(positions.get(pos_id) or 0), 2)

	def add_amount(parent, tag, value):
		el = ET.SubElement(parent, f"{_NS}{tag}")
		el.text = f"{value:.2f}"
		return el

	def add_sort_sum(parent, tag, pos_id, default_text):
		"""SortSumType: mandatory Text + Sum."""
		wrapper = ET.SubElement(parent, f"{_NS}{tag}")
		ET.SubElement(wrapper, f"{_NS}Text").text = descriptions.get(pos_id) or default_text
		ET.SubElement(wrapper, f"{_NS}Sum").text = f"{amount(pos_id):.2f}"

	# 1 — salary
	if amount("1"):
		add_amount(s, "Income", amount("1"))

	# 2.x — fringe benefits (form: 2.1 board/lodging, 2.2 company car, 2.3 other)
	if amount("2.1") or amount("2.2") or amount("2.3"):
		fringe = ET.SubElement(s, f"{_NS}FringeBenefits")
		if amount("2.1"):
			add_amount(fringe, "FoodLodging", amount("2.1"))
		if amount("2.2"):
			add_amount(fringe, "CompanyCar", amount("2.2"))
		if amount("2.3"):
			other = ET.SubElement(fringe, f"{_NS}Other")
			ET.SubElement(other, f"{_NS}Text").text = descriptions.get("2.3") or "Autres"
			ET.SubElement(other, f"{_NS}Sum").text = f"{amount('2.3'):.2f}"

	# //// Neoffice — the French wording of these sort labels is DATA, not a UI string:
	# //// it is the text the tax authority reads back from the 2D barcode of the salary
	# //// certificate, and the Lohnausweis specification prescribes the wording per
	# //// language. RULE #00 does not apply — do NOT translate them to English, and do
	# //// not route them through `_()`: the certificate's language is the employee's,
	# //// not the reader's. Same reason for "Autres" above (issue #239).
	# 3-7
	if amount("3"):
		add_sort_sum(s, "SporadicBenefits", "3", "Prestations non périodiques")
	if amount("4"):
		add_sort_sum(s, "CapitalPayment", "4", "Prestations en capital")
	if amount("5"):
		add_amount(s, "OwnershipRight", amount("5"))
	if amount("6"):
		add_amount(s, "BoardOfDirectorsRemuneration", amount("6"))
	if amount("7"):
		add_sort_sum(s, "OtherBenefits", "7", "Autres prestations")

	# 8 — gross income (required)
	add_amount(s, "GrossIncome", amount("8"))

	# 9 / 10.x
	if amount("9"):
		add_amount(s, "AHV-ALV-NBUV-AVS-AC-AANP-Contribution", amount("9"))
	if amount("10.1") or amount("10.2"):
		bvg = ET.SubElement(s, f"{_NS}BVG-LPP-Contribution")
		if amount("10.1"):
			add_amount(bvg, "Regular", amount("10.1"))
		if amount("10.2"):
			add_amount(bvg, "Purchase", amount("10.2"))

	# 11 — net income (required)
	add_amount(s, "NetIncome", amount("11"))

	# 12
	if amount("12"):
		add_amount(s, "DeductionAtSource", amount("12"))

	# 13 — expenses: first the expense regulation approved by a canton (Wegleitung Rz 55, 56, 65)
	standard = certificate_data.get("standard_remarks") or {}
	regulation = standard.get("expense_regulation")
	if regulation and regulation.get("canton") and regulation.get("date"):
		rule = ET.SubElement(ET.SubElement(s, f"{_NS}ChargesRule"), f"{_NS}WithRegulation")
		ET.SubElement(rule, f"{_NS}Allowed").text = str(regulation["date"])[:10]
		ET.SubElement(rule, f"{_NS}Canton").text = regulation["canton"]

	has_effective = amount("13.1.1") or amount("13.1.2")
	has_lumpsum = amount("13.2.1") or amount("13.2.2") or amount("13.2.3")
	if has_effective or has_lumpsum or amount("13.3"):
		charges = ET.SubElement(s, f"{_NS}Charges")
		if has_effective:
			eff = ET.SubElement(charges, f"{_NS}Effective")
			if amount("13.1.1"):
				add_amount(eff, "TravelFoodAccommodation", amount("13.1.1"))
			if amount("13.1.2"):
				other = ET.SubElement(eff, f"{_NS}Other")
				ET.SubElement(other, f"{_NS}Text").text = (
					descriptions.get("13.1.2") or "Autres frais effectifs"
				)
				ET.SubElement(other, f"{_NS}Sum").text = f"{amount('13.1.2'):.2f}"
		if has_lumpsum:
			lump = ET.SubElement(charges, f"{_NS}LumpSum")
			if amount("13.2.1"):
				add_amount(lump, "Representation", amount("13.2.1"))
			if amount("13.2.2"):
				add_amount(lump, "Car", amount("13.2.2"))
			if amount("13.2.3"):
				other = ET.SubElement(lump, f"{_NS}Other")
				ET.SubElement(other, f"{_NS}Text").text = (
					descriptions.get("13.2.3") or "Autres frais forfaitaires"
				)
				ET.SubElement(other, f"{_NS}Sum").text = f"{amount('13.2.3'):.2f}"
		if amount("13.3"):
			add_amount(charges, "Education", amount("13.3"))

	# 14 — other fringe benefits (free text on the official form)
	pos14_text = descriptions.get("14") or ""
	if not pos14_text and amount("14"):
		pos14_text = f"{amount('14'):.2f}"
	if pos14_text:
		ET.SubElement(s, f"{_NS}OtherFringeBenefits").text = pos14_text

	# 15 — remarks: the official catalogue as StandardRemark (the reader prints its own text),
	# then the free text. A caller without "remark" passes box 15 as printed.
	_add_standard_remarks(s, standard)
	remarks = certificate_data["remark"] if "remark" in certificate_data else positions.get("15") or ""
	if remarks:
		ET.SubElement(s, f"{_NS}Remark").text = str(remarks)

	xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
	buf = io.StringIO()
	ET.ElementTree(root).write(buf, encoding="unicode", xml_declaration=False)
	return (xml_declaration + buf.getvalue()).encode("utf-8")


# ---------------------------------------------------------------------------
# ZIP container + control headers
# ---------------------------------------------------------------------------
def build_txab_zip(xml_bytes):
	"""Pack the TxAB XML into an Info-ZIP archive with one entry "txab".

	Annex 5 chapter 2.1: the XML file is compressed in Info-ZIP format and
	the name of the zip entry is "txab" (no file extension, to save space).
	"""
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
		zf.writestr(ZIP_ENTRY_NAME, xml_bytes)
	return buf.getvalue()


def split_into_symbols(zip_bytes, identification=None, max_payload=MAX_PAYLOAD_PER_SYMBOL):
	"""Split the ZIP data into barcode symbols, each with its 14-byte header.

	Args:
		zip_bytes: the Info-ZIP archive bytes
		identification: optional 4 bytes shared by all symbols of this file
			(random when omitted, as recommended by the specification)
		max_payload: maximum ZIP bytes per symbol

	Returns:
		list of bytes objects (header + payload), ready for PDF417 encoding
	"""
	if identification is None:
		identification = os.urandom(4)
	if len(identification) != 4:
		raise ValueError("identification must be exactly 4 bytes")

	chunks = [zip_bytes[i : i + max_payload] for i in range(0, len(zip_bytes), max_payload)] or [b""]
	total = len(chunks)
	if total > 99:
		raise ValueError(f"certificate data needs {total} barcodes; maximum is 99")

	symbols = []
	for index, chunk in enumerate(chunks, start=1):
		size = HEADER_SIZE + len(chunk)
		header = bytes(
			[
				identification[0], identification[1], identification[2], identification[3],
				COMPRESSION_ZIP,
				(size >> 16) & 0xFF, (size >> 8) & 0xFF, size & 0xFF,
				1 if index == 1 else 2,
				CONTROL_VERSION,
				index // 10, index % 10,
				total // 10, total % 10,
			]
		)  # fmt: skip
		symbols.append(header + chunk)
	return symbols


def parse_symbol_header(symbol_bytes):
	"""Decode a 14-byte control header (used by tests and diagnostics)."""
	if len(symbol_bytes) < HEADER_SIZE:
		raise ValueError("symbol shorter than the 14-byte control header")
	h = symbol_bytes[:HEADER_SIZE]
	return {
		"identification": h[0:4],
		"compression": chr(h[4]),
		"size": (h[5] << 16) | (h[6] << 8) | h[7],
		"page_marker": h[8],
		"control_version": h[9],
		"symbol_number": h[10] * 10 + h[11],
		"symbol_count": h[12] * 10 + h[13],
		"payload": symbol_bytes[HEADER_SIZE:],
	}


# ---------------------------------------------------------------------------
# Barcode rendering
# ---------------------------------------------------------------------------
def generate_pdf417_barcodes(symbols):
	"""Render each symbol as a PDF417 PNG (annex 5: EC level 2, 15 columns)."""
	from pdf417gen import render_image

	images = []
	for symbol in symbols:
		codes = pdf417_code_words(symbol, PDF417_COLUMNS, PDF417_SECURITY_LEVEL)
		img = render_image(
			codes,
			scale=PDF417_SCALE,
			ratio=PDF417_RATIO,
			padding=PDF417_PADDING,
		)
		buf = io.BytesIO()
		img.save(buf, format="PNG")
		images.append(buf.getvalue())
	return images


def pdf417_code_words(symbol, columns, security_level):
	"""The PDF417 rows of ``symbol`` in Byte compaction only: 6 bytes in 5 codewords.

	pdf417gen.encode() splits its input by character class and switches mode at every run,
	which on compressed data costs up to 1.5 codewords per byte (1477 for 986 random bytes,
	pdf417gen 0.8.1). The first symbol of a certificate took 59 rows; shrunk into box H of the
	form (250 x 120 px) its module fell to ~0.17 mm, below what scanners read reliably. One mode
	gives ~33 rows for the same bytes. Same steps as pdf417gen.encoding.encode otherwise.
	"""
	import math

	from pdf417gen.compaction import BYTE_LATCH, BYTE_LATCH_ALT
	from pdf417gen.compaction.byte import compact_bytes
	from pdf417gen.encoding import encode_rows, get_padding, validate_barcode_size
	from pdf417gen.error_correction import compute_error_correction_code_words
	from pdf417gen.util import chunks

	data = list(symbol)
	data_words = [BYTE_LATCH_ALT if len(data) % 6 == 0 else BYTE_LATCH, *compact_bytes(data)]
	ec_count = 2 ** (security_level + 1)
	padding = get_padding(len(data_words), ec_count, columns)
	length_descriptor = len(data_words) + len(padding) + 1
	validate_barcode_size(length_descriptor, math.ceil((length_descriptor + ec_count) / columns))
	words = [length_descriptor, *data_words, *padding]
	words += compute_error_correction_code_words(words, security_level)
	return list(encode_rows(list(chunks(words, columns)), columns, security_level))


def generate_code128c(identifier):
	"""Generate an internal CODE128 1D identifier barcode (not part of the
	Swissdec specification — kept as a human/scanner-friendly document ID)."""
	import barcode
	from barcode.writer import ImageWriter

	writer = ImageWriter()
	writer.set_options(
		{
			"module_height": 12.0,
			"module_width": 0.3,
			"quiet_zone": 5.0,
			"font_size": 8,
			"text_distance": 3.0,
		}
	)
	code = barcode.get("code128", identifier, writer=writer)
	buf = io.BytesIO()
	code.write(buf)
	return buf.getvalue()


def build_certificate_identifier(company_uid, employee_avs, year):
	"""Build a 16-digit numeric identifier for the CODE128 barcode.

	Format: last 6 digits of UID + last 6 digits of AVS + 4-digit year.
	"""
	uid_digits = re.sub(r"\D", "", company_uid or "")
	avs_digits = re.sub(r"\D", "", employee_avs or "")
	year_str = re.sub(r"\D", "", str(year or "")) or "0000"

	uid_part = uid_digits[-6:].zfill(6)
	avs_part = avs_digits[-6:].zfill(6)
	year_part = year_str[-4:].zfill(4)

	return uid_part + avs_part + year_part


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def generate_barcode_page_data(certificate_data):
	"""End-to-end barcode generation from certificate data.

	Pipeline: TxAB XML → Info-ZIP ("txab") → symbols with 14-byte headers
	→ PDF417 (EC 2) → PNG, plus the internal CODE128 identifier.

	Returns:
		dict with keys:
			- pdf417_images: list of base64-encoded PNG strings
			- code128c_image: base64-encoded PNG string
			- identifier: 16-digit string
			- xml_preview: str (raw TxAB XML for debugging)
			- page_count: int (number of PDF417 symbols)
	"""
	xml_bytes = generate_txab_xml(certificate_data)
	zip_bytes = build_txab_zip(xml_bytes)
	symbols = split_into_symbols(zip_bytes)
	pdf417_pngs = generate_pdf417_barcodes(symbols)

	employer = certificate_data.get("employer", {})
	employee = certificate_data.get("employee", {})
	identifier = build_certificate_identifier(
		employer.get("uid_bfs", ""),
		employee.get("avs_number", ""),
		certificate_data.get("fiscal_year", ""),
	)
	code128c_png = generate_code128c(identifier)

	return {
		"pdf417_images": [base64.b64encode(png).decode("ascii") for png in pdf417_pngs],
		"code128c_image": base64.b64encode(code128c_png).decode("ascii"),
		"identifier": identifier,
		"xml_preview": xml_bytes.decode("utf-8"),
		"page_count": len(pdf417_pngs),
	}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _add_standard_remarks(salary, standard):
	"""StandardRemark children, in the order of StandardRemarkType (TxAB 6.0)."""
	flags = (
		("tax_at_source", "TaxAtSourcePeriodForObjection"),
		("short_time_work", "ShortTimeWorkCompensation"),
		("part_time", "PartTimeEmployment"),
	)
	rectificate = standard.get("rectificate")
	count = int(standard.get("number_of_certificates") or 0)
	if not (any(standard.get(key) for key, _tag in flags) or count > 1 or rectificate):
		return
	remark = ET.SubElement(salary, f"{_NS}StandardRemark")
	for key, tag in flags:
		if standard.get(key):
			ET.SubElement(remark, f"{_NS}{tag}")
	if count > 1:
		ET.SubElement(remark, f"{_NS}NumberOfSalaryCertificate").text = str(count)
	if rectificate:
		element = ET.SubElement(remark, f"{_NS}Rectificate")
		ET.SubElement(element, f"{_NS}OriginalDate").text = str(rectificate["date"])[:10]
		ET.SubElement(element, f"{_NS}OriginalDocID").text = str(rectificate["doc_id"])


def _creation_date(value):
	"""xs:dateTime, to the second: when the certificate was issued (now for a draft)."""
	from datetime import datetime

	moment = datetime.fromisoformat(str(value)) if value else datetime.now()
	return moment.replace(microsecond=0, tzinfo=None).isoformat()


def _limit(text, length=None):
	"""Whitespace collapsed (the schema's own rule), then cut to ``length``."""
	text = " ".join(str(text or "").split())
	return text[:length] if length else text


def _format_uid(uid):
	"""Normalize a UID to the official CHE-XXX.XXX.XXX presentation."""
	digits = re.sub(r"\D", "", uid or "")
	if len(digits) == 9:
		return f"CHE-{digits[0:3]}.{digits[3:6]}.{digits[6:9]}"
	return ""


def _format_avs(avs):
	"""Normalize an AVS number to the dotted 756.XXXX.XXXX.XX format
	required by SV-AS-NumberType."""
	digits = re.sub(r"\D", "", avs or "")
	if len(digits) == 13:
		return f"{digits[0:3]}.{digits[3:7]}.{digits[7:11]}.{digits[11:13]}"
	return ""


def _extract_street(address):
	"""Extract first line from multi-line address as street."""
	if not address:
		return ""
	lines = [line.strip() for line in address.split("\n") if line.strip()]
	return lines[0] if lines else ""


def _certificate_period(fiscal_year, date_of_joining, relieving_date):
	"""Compute the certificate period bounded by entry/exit within the year."""
	year = re.sub(r"\D", "", str(fiscal_year or ""))[:4] or "0000"
	date_from = f"{year}-01-01"
	date_until = f"{year}-12-31"
	if date_of_joining and str(date_of_joining)[:4] == year:
		date_from = str(date_of_joining)[:10]
	if relieving_date and str(relieving_date)[:4] == year:
		date_until = str(relieving_date)[:10]
	return date_from, date_until


def _split_person_name(employee):
	"""Return (first_name, last_name) from explicit fields or the full name."""
	first = (employee.get("first_name") or "").strip()
	last = (employee.get("last_name") or "").strip()
	if first or last:
		return first, last
	parts = (employee.get("name") or "").split()
	if not parts:
		return "", ""
	if len(parts) == 1:
		return "", parts[0]
	return parts[0], " ".join(parts[1:])


def _fallback_doc_id(company_uid, employee_avs, year):
	"""Deterministic DocID when the caller provides no certificate id."""
	return "CERT-" + build_certificate_identifier(company_uid, employee_avs, year)
