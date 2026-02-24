# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""eCH-0270 barcode generation for Swiss Salary Certificates (Lohnausweis).

Generates PDF417 2D barcodes and CODE128C 1D identifier barcodes for
the official Swiss salary certificate (Form 11). The barcode encodes
certificate data as compressed XML for automatic reading by cantonal
tax administrations.

Pipeline: Certificate data → XML → DEFLATE compress → PDF417 → PNG

This module has no Frappe dependency; all functions are pure Python
for maximum testability. External libraries (pdf417gen, python-barcode)
are imported lazily inside function bodies.
"""

import base64
import io
import re
import zlib
import xml.etree.ElementTree as ET

# All Form 11 position IDs in order
POSITION_IDS = [
	"1", "2.1", "2.2", "2.3", "3", "4", "5", "6", "7",
	"8", "9", "10.1", "10.2", "11", "12",
	"13.1", "13.2", "13.3", "14", "15",
]

# eCH-0270 XML namespace
ECH_0270_NS = "urn:ch:ech:0270:1"
_NS = f"{{{ECH_0270_NS}}}"

# PDF417 parameters per eCH-0270 specification
PDF417_COLUMNS = 13
PDF417_SECURITY_LEVEL = 4
PDF417_SCALE = 3
PDF417_RATIO = 3
PDF417_PADDING = 20

# Register default namespace so output uses xmlns= on root, not ns0: prefix
ET.register_namespace("", ECH_0270_NS)


def generate_lohnausweis_xml(certificate_data):
	"""Generate eCH-0270-compliant XML from salary certificate data.

	Args:
		certificate_data: dict with keys:
			- employer: dict (name, address, uid_bfs, zip_code, city)
			- employee: dict (name, avs_number, date_of_birth, date_of_joining, relieving_date)
			- fiscal_year: str (e.g. "2025")
			- posting_date: str (ISO date)
			- positions: dict mapping position IDs to values (float for 1-14, str for 15)

	Returns:
		bytes: UTF-8 encoded XML
	"""
	root = ET.Element(f"{_NS}SalaryCertificate")
	root.set("version", "1.0")

	# Employer section
	employer = certificate_data.get("employer", {})
	emp_elem = ET.SubElement(root, f"{_NS}Employer")
	ET.SubElement(emp_elem, f"{_NS}UID").text = _normalize_uid(employer.get("uid_bfs", ""))
	ET.SubElement(emp_elem, f"{_NS}Name").text = employer.get("name", "")
	addr_elem = ET.SubElement(emp_elem, f"{_NS}Address")
	ET.SubElement(addr_elem, f"{_NS}Street").text = _extract_street(employer.get("address", ""))
	ET.SubElement(addr_elem, f"{_NS}ZipCode").text = employer.get("zip_code", "")
	ET.SubElement(addr_elem, f"{_NS}City").text = employer.get("city", "")

	# Employee section
	employee = certificate_data.get("employee", {})
	ee_elem = ET.SubElement(root, f"{_NS}Employee")
	ET.SubElement(ee_elem, f"{_NS}AVSNumber").text = _normalize_avs(employee.get("avs_number", ""))
	ET.SubElement(ee_elem, f"{_NS}Name").text = employee.get("name", "")
	ET.SubElement(ee_elem, f"{_NS}DateOfBirth").text = employee.get("date_of_birth", "")
	ET.SubElement(ee_elem, f"{_NS}EntryDate").text = employee.get("date_of_joining", "")
	leaving = employee.get("relieving_date", "")
	if leaving:
		ET.SubElement(ee_elem, f"{_NS}LeavingDate").text = leaving

	# Period section
	period_elem = ET.SubElement(root, f"{_NS}Period")
	ET.SubElement(period_elem, f"{_NS}Year").text = str(certificate_data.get("fiscal_year", ""))
	ET.SubElement(period_elem, f"{_NS}CertificateDate").text = certificate_data.get("posting_date", "")

	# Positions section
	positions = certificate_data.get("positions", {})
	pos_elem = ET.SubElement(root, f"{_NS}Positions")
	for pos_id in POSITION_IDS:
		value = positions.get(pos_id, 0)
		pos_child = ET.SubElement(pos_elem, f"{_NS}Position")
		pos_child.set("id", pos_id)
		if pos_id == "15":
			# Position 15 is text (remarks)
			pos_child.set("text", str(value) if value else "")
		else:
			pos_child.set("amount", f"{float(value):.2f}")

	# Serialize to XML bytes
	xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
	tree = ET.ElementTree(root)
	buf = io.StringIO()
	tree.write(buf, encoding="unicode", xml_declaration=False)
	return (xml_declaration + buf.getvalue()).encode("utf-8")


def compress_xml(xml_bytes):
	"""DEFLATE-compress XML data per eCH-0270 spec.

	Uses zlib compress (DEFLATE with zlib header). The eCH-0270 standard
	specifies RFC 1950/1951 DEFLATE compression.

	Args:
		xml_bytes: UTF-8 encoded XML bytes

	Returns:
		bytes: Compressed data
	"""
	return zlib.compress(xml_bytes, level=9)


def generate_pdf417_barcodes(compressed_data):
	"""Generate PDF417 barcode image(s) from compressed data.

	Uses eCH-0270 parameters: 13 columns, Error Correction Level 4.
	For typical salary certificates (~400-600 bytes compressed),
	a single barcode is sufficient.

	Args:
		compressed_data: DEFLATE-compressed bytes

	Returns:
		list of PNG image bytes (typically one element)
	"""
	from pdf417gen import encode, render_image

	codes = encode(
		compressed_data,
		columns=PDF417_COLUMNS,
		security_level=PDF417_SECURITY_LEVEL,
	)
	img = render_image(
		codes,
		scale=PDF417_SCALE,
		ratio=PDF417_RATIO,
		padding=PDF417_PADDING,
	)
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	return [buf.getvalue()]


def generate_code128c(identifier):
	"""Generate CODE128 1D barcode image.

	Args:
		identifier: Numeric string identifier

	Returns:
		bytes: PNG image of the CODE128 barcode
	"""
	import barcode
	from barcode.writer import ImageWriter

	writer = ImageWriter()
	writer.set_options({
		"module_height": 12.0,
		"module_width": 0.3,
		"quiet_zone": 5.0,
		"font_size": 8,
		"text_distance": 3.0,
	})
	code = barcode.get("code128", identifier, writer=writer)
	buf = io.BytesIO()
	code.write(buf)
	return buf.getvalue()


def build_certificate_identifier(company_uid, employee_avs, year):
	"""Build a 16-digit numeric identifier for the CODE128C barcode.

	Format: last 6 digits of UID + last 6 digits of AVS + 4-digit year.
	Both UID and AVS are stripped of non-digit characters first.

	Args:
		company_uid: CHE-XXX.XXX.XXX or similar format
		employee_avs: 756.XXXX.XXXX.XX format
		year: fiscal year string (e.g. "2025")

	Returns:
		str: 16-digit numeric identifier
	"""
	uid_digits = re.sub(r"\D", "", company_uid or "")
	avs_digits = re.sub(r"\D", "", employee_avs or "")
	year_str = str(year or "0000")

	# Take last 6 digits of each, pad with zeros if needed
	uid_part = uid_digits[-6:].zfill(6)
	avs_part = avs_digits[-6:].zfill(6)
	year_part = year_str[-4:].zfill(4)

	return uid_part + avs_part + year_part


def generate_barcode_page_data(certificate_data):
	"""End-to-end barcode generation from certificate data.

	Orchestrates: XML generation → compression → PDF417 encoding → CODE128C.

	Args:
		certificate_data: dict (see generate_lohnausweis_xml for structure)

	Returns:
		dict with keys:
			- pdf417_images: list of base64-encoded PNG strings
			- code128c_image: base64-encoded PNG string
			- identifier: 16-digit string
			- xml_preview: str (raw XML for debugging)
			- page_count: int (number of barcode pages)
	"""
	# Step 1: Generate XML
	xml_bytes = generate_lohnausweis_xml(certificate_data)

	# Step 2: Compress
	compressed = compress_xml(xml_bytes)

	# Step 3: Generate PDF417 barcode(s)
	pdf417_pngs = generate_pdf417_barcodes(compressed)

	# Step 4: Generate CODE128C identifier
	employer = certificate_data.get("employer", {})
	employee = certificate_data.get("employee", {})
	identifier = build_certificate_identifier(
		employer.get("uid_bfs", ""),
		employee.get("avs_number", ""),
		certificate_data.get("fiscal_year", ""),
	)
	code128c_png = generate_code128c(identifier)

	# Step 5: Encode to base64
	pdf417_b64 = [base64.b64encode(png).decode("ascii") for png in pdf417_pngs]
	code128c_b64 = base64.b64encode(code128c_png).decode("ascii")

	return {
		"pdf417_images": pdf417_b64,
		"code128c_image": code128c_b64,
		"identifier": identifier,
		"xml_preview": xml_bytes.decode("utf-8"),
		"page_count": len(pdf417_pngs),
	}


def _normalize_uid(uid):
	"""Strip non-alphanumeric characters from UID-BFS, keeping CHE prefix."""
	return re.sub(r"[^A-Za-z0-9]", "", uid or "")


def _normalize_avs(avs):
	"""Strip dots and spaces from AVS number."""
	return re.sub(r"[.\s]", "", avs or "")


def _extract_street(address):
	"""Extract first line from multi-line address as street."""
	if not address:
		return ""
	lines = [line.strip() for line in address.split("\n") if line.strip()]
	return lines[0] if lines else ""
