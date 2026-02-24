# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import base64
import sys
import types
import unittest
import xml.etree.ElementTree as ET
import zlib

# Mock frappe module so hrms/__init__.py doesn't fail outside bench
if "frappe" not in sys.modules:
	_frappe = types.ModuleType("frappe")
	_frappe.__version__ = "15.0.0"
	_frappe._ = lambda x: x
	sys.modules["frappe"] = _frappe

from hrms.regional.switzerland.lohnausweis_barcode import (
	ECH_0270_NS,
	POSITION_IDS,
	build_certificate_identifier,
	compress_xml,
	generate_barcode_page_data,
	generate_code128c,
	generate_lohnausweis_xml,
	generate_pdf417_barcodes,
)

# Namespace map for XPath queries
_NSM = {"n": ECH_0270_NS}
_NS = f"{{{ECH_0270_NS}}}"


def _make_certificate_data(**overrides):
	"""Create sample certificate data for tests."""
	data = {
		"employer": {
			"name": "Neoffice SA",
			"address": "Route de Berne 1\n1000 Lausanne",
			"uid_bfs": "CHE-123.456.789",
			"zip_code": "1000",
			"city": "Lausanne",
		},
		"employee": {
			"name": "Jean Dupont",
			"avs_number": "756.1234.5678.97",
			"date_of_birth": "1985-06-15",
			"date_of_joining": "2020-01-01",
			"relieving_date": "",
		},
		"fiscal_year": "2025",
		"posting_date": "2026-01-15",
		"positions": {
			"1": 96000.0,
			"2.1": 0.0,
			"2.2": 0.0,
			"2.3": 0.0,
			"3": 5000.0,
			"4": 0.0,
			"5": 0.0,
			"6": 0.0,
			"7": 1200.0,
			"8": 102200.0,
			"9": 7776.0,
			"10.1": 1593.96,
			"10.2": 0.0,
			"11": 92830.04,
			"12": 0.0,
			"13.1": 3600.0,
			"13.2": 0.0,
			"13.3": 2400.0,
			"14": 0.0,
			"15": "Generated from 12 salary slips for fiscal year 2025.",
		},
	}
	data.update(overrides)
	return data


class TestXmlGeneration(unittest.TestCase):
	"""Tests for eCH-0270 XML generation."""

	def test_xml_is_valid(self):
		"""Generated XML parses without error."""
		xml_bytes = generate_lohnausweis_xml(_make_certificate_data())
		root = ET.fromstring(xml_bytes)
		self.assertEqual(root.tag, f"{_NS}SalaryCertificate")

	def test_xml_has_declaration(self):
		"""XML starts with proper declaration."""
		xml_bytes = generate_lohnausweis_xml(_make_certificate_data())
		self.assertTrue(xml_bytes.startswith(b'<?xml version="1.0" encoding="UTF-8"?>'))

	def test_xml_namespace_and_version(self):
		"""Root element has correct namespace and version."""
		xml_bytes = generate_lohnausweis_xml(_make_certificate_data())
		root = ET.fromstring(xml_bytes)
		# Namespace is in the tag, not as an attribute when using proper NS
		self.assertTrue(root.tag.startswith(f"{{{ECH_0270_NS}}}"))
		self.assertEqual(root.get("version"), "1.0")

	def test_xml_employer_data(self):
		"""Employer data is correctly encoded."""
		xml_bytes = generate_lohnausweis_xml(_make_certificate_data())
		root = ET.fromstring(xml_bytes)
		employer = root.find("n:Employer", _NSM)
		self.assertEqual(employer.find("n:UID", _NSM).text, "CHE123456789")
		self.assertEqual(employer.find("n:Name", _NSM).text, "Neoffice SA")
		self.assertEqual(employer.find("n:Address/n:ZipCode", _NSM).text, "1000")
		self.assertEqual(employer.find("n:Address/n:City", _NSM).text, "Lausanne")

	def test_xml_employee_data(self):
		"""Employee data is correctly encoded."""
		xml_bytes = generate_lohnausweis_xml(_make_certificate_data())
		root = ET.fromstring(xml_bytes)
		employee = root.find("n:Employee", _NSM)
		self.assertEqual(employee.find("n:AVSNumber", _NSM).text, "7561234567897")
		self.assertEqual(employee.find("n:Name", _NSM).text, "Jean Dupont")
		self.assertEqual(employee.find("n:DateOfBirth", _NSM).text, "1985-06-15")

	def test_xml_avs_number_normalized(self):
		"""AVS number has dots stripped."""
		xml_bytes = generate_lohnausweis_xml(_make_certificate_data())
		root = ET.fromstring(xml_bytes)
		avs = root.find("n:Employee/n:AVSNumber", _NSM).text
		self.assertNotIn(".", avs)

	def test_xml_uid_normalized(self):
		"""UID has separators stripped."""
		xml_bytes = generate_lohnausweis_xml(_make_certificate_data())
		root = ET.fromstring(xml_bytes)
		uid = root.find("n:Employer/n:UID", _NSM).text
		self.assertNotIn("-", uid)
		self.assertNotIn(".", uid)

	def test_xml_all_positions_present(self):
		"""All 20 Form 11 positions appear in XML."""
		xml_bytes = generate_lohnausweis_xml(_make_certificate_data())
		root = ET.fromstring(xml_bytes)
		positions = root.findall("n:Positions/n:Position", _NSM)
		ids = [p.get("id") for p in positions]
		self.assertEqual(ids, POSITION_IDS)

	def test_xml_position_amounts(self):
		"""Numeric positions have correct amounts."""
		xml_bytes = generate_lohnausweis_xml(_make_certificate_data())
		root = ET.fromstring(xml_bytes)
		positions = root.findall("n:Positions/n:Position", _NSM)
		pos_map = {p.get("id"): p for p in positions}
		self.assertEqual(pos_map["1"].get("amount"), "96000.00")
		self.assertEqual(pos_map["10.1"].get("amount"), "1593.96")

	def test_xml_position_15_is_text(self):
		"""Position 15 uses text attribute, not amount."""
		xml_bytes = generate_lohnausweis_xml(_make_certificate_data())
		root = ET.fromstring(xml_bytes)
		positions = root.findall("n:Positions/n:Position", _NSM)
		pos15 = [p for p in positions if p.get("id") == "15"][0]
		self.assertIsNone(pos15.get("amount"))
		self.assertIn("12 salary slips", pos15.get("text"))

	def test_xml_all_zero_positions(self):
		"""All zero amounts produce valid XML."""
		data = _make_certificate_data()
		for k in data["positions"]:
			data["positions"][k] = 0 if k != "15" else ""
		xml_bytes = generate_lohnausweis_xml(data)
		root = ET.fromstring(xml_bytes)
		self.assertIsNotNone(root)

	def test_xml_no_leaving_date(self):
		"""No LeavingDate element when employee hasn't left."""
		data = _make_certificate_data()
		data["employee"]["relieving_date"] = ""
		xml_bytes = generate_lohnausweis_xml(data)
		root = ET.fromstring(xml_bytes)
		leaving = root.find("n:Employee/n:LeavingDate", _NSM)
		self.assertIsNone(leaving)

	def test_xml_with_leaving_date(self):
		"""LeavingDate element present when employee has left."""
		data = _make_certificate_data()
		data["employee"]["relieving_date"] = "2025-06-30"
		xml_bytes = generate_lohnausweis_xml(data)
		root = ET.fromstring(xml_bytes)
		leaving = root.find("n:Employee/n:LeavingDate", _NSM)
		self.assertIsNotNone(leaving)
		self.assertEqual(leaving.text, "2025-06-30")

	def test_xml_street_extracted_from_multiline(self):
		"""Street is extracted as first line of multi-line address."""
		xml_bytes = generate_lohnausweis_xml(_make_certificate_data())
		root = ET.fromstring(xml_bytes)
		street = root.find("n:Employer/n:Address/n:Street", _NSM).text
		self.assertEqual(street, "Route de Berne 1")


class TestCompression(unittest.TestCase):
	"""Tests for DEFLATE compression."""

	def test_compress_and_decompress_roundtrip(self):
		"""Compressed data can be decompressed back to original."""
		xml = generate_lohnausweis_xml(_make_certificate_data())
		compressed = compress_xml(xml)
		decompressed = zlib.decompress(compressed)
		self.assertEqual(decompressed, xml)

	def test_compressed_smaller_than_original(self):
		"""Compressed output is smaller than XML input."""
		xml = generate_lohnausweis_xml(_make_certificate_data())
		compressed = compress_xml(xml)
		self.assertLess(len(compressed), len(xml))

	def test_typical_certificate_under_1500_bytes(self):
		"""A typical certificate compresses to well under 1500 bytes (single barcode)."""
		xml = generate_lohnausweis_xml(_make_certificate_data())
		compressed = compress_xml(xml)
		self.assertLess(len(compressed), 1500)


class TestPdf417Generation(unittest.TestCase):
	"""Tests for PDF417 barcode generation."""

	def test_single_barcode_for_typical_data(self):
		"""Typical data produces exactly one barcode."""
		xml = generate_lohnausweis_xml(_make_certificate_data())
		compressed = compress_xml(xml)
		barcodes = generate_pdf417_barcodes(compressed)
		self.assertEqual(len(barcodes), 1)

	def test_barcode_is_valid_png(self):
		"""Generated barcode is a valid PNG image."""
		xml = generate_lohnausweis_xml(_make_certificate_data())
		compressed = compress_xml(xml)
		barcodes = generate_pdf417_barcodes(compressed)
		# PNG magic bytes
		self.assertTrue(barcodes[0].startswith(b"\x89PNG"))

	def test_barcode_reasonable_size(self):
		"""Barcode image is a reasonable size (not empty, not huge)."""
		xml = generate_lohnausweis_xml(_make_certificate_data())
		compressed = compress_xml(xml)
		barcodes = generate_pdf417_barcodes(compressed)
		size = len(barcodes[0])
		self.assertGreater(size, 100)
		self.assertLess(size, 100000)


class TestCode128CGeneration(unittest.TestCase):
	"""Tests for CODE128C barcode generation."""

	def test_code128c_produces_png(self):
		"""CODE128C barcode is a valid PNG image."""
		png = generate_code128c("1234567890123456")
		self.assertTrue(png.startswith(b"\x89PNG"))

	def test_code128c_reasonable_size(self):
		"""CODE128C image is a reasonable size."""
		png = generate_code128c("1234567890123456")
		self.assertGreater(len(png), 100)
		self.assertLess(len(png), 50000)


class TestIdentifierGeneration(unittest.TestCase):
	"""Tests for the 16-digit certificate identifier."""

	def test_identifier_is_16_digits(self):
		"""Identifier is exactly 16 digits."""
		ident = build_certificate_identifier("CHE-123.456.789", "756.1234.5678.97", "2025")
		self.assertEqual(len(ident), 16)
		self.assertTrue(ident.isdigit())

	def test_identifier_deterministic(self):
		"""Same input always produces same output."""
		a = build_certificate_identifier("CHE-123.456.789", "756.1234.5678.97", "2025")
		b = build_certificate_identifier("CHE-123.456.789", "756.1234.5678.97", "2025")
		self.assertEqual(a, b)

	def test_identifier_different_for_different_year(self):
		"""Different year produces different identifier."""
		a = build_certificate_identifier("CHE-123.456.789", "756.1234.5678.97", "2025")
		b = build_certificate_identifier("CHE-123.456.789", "756.1234.5678.97", "2024")
		self.assertNotEqual(a, b)

	def test_identifier_different_for_different_employee(self):
		"""Different employee produces different identifier."""
		a = build_certificate_identifier("CHE-123.456.789", "756.1234.5678.97", "2025")
		b = build_certificate_identifier("CHE-123.456.789", "756.9876.5432.10", "2025")
		self.assertNotEqual(a, b)

	def test_identifier_handles_empty_inputs(self):
		"""Empty inputs produce a valid 16-digit identifier (zero-padded)."""
		ident = build_certificate_identifier("", "", "")
		self.assertEqual(len(ident), 16)
		self.assertTrue(ident.isdigit())


class TestEndToEnd(unittest.TestCase):
	"""Integration tests for the full barcode generation pipeline."""

	def test_barcode_page_data_structure(self):
		"""generate_barcode_page_data returns expected keys."""
		result = generate_barcode_page_data(_make_certificate_data())
		self.assertIn("pdf417_images", result)
		self.assertIn("code128c_image", result)
		self.assertIn("identifier", result)
		self.assertIn("xml_preview", result)
		self.assertIn("page_count", result)

	def test_barcode_page_data_types(self):
		"""Return values have correct types."""
		result = generate_barcode_page_data(_make_certificate_data())
		self.assertIsInstance(result["pdf417_images"], list)
		self.assertIsInstance(result["code128c_image"], str)
		self.assertIsInstance(result["identifier"], str)
		self.assertIsInstance(result["xml_preview"], str)
		self.assertIsInstance(result["page_count"], int)

	def test_base64_images_valid(self):
		"""Base64 images can be decoded back to valid PNG."""
		result = generate_barcode_page_data(_make_certificate_data())
		for b64_img in result["pdf417_images"]:
			png = base64.b64decode(b64_img)
			self.assertTrue(png.startswith(b"\x89PNG"))
		png = base64.b64decode(result["code128c_image"])
		self.assertTrue(png.startswith(b"\x89PNG"))

	def test_xml_preview_is_valid_xml(self):
		"""XML preview string is valid XML."""
		result = generate_barcode_page_data(_make_certificate_data())
		root = ET.fromstring(result["xml_preview"])
		self.assertEqual(root.tag, f"{_NS}SalaryCertificate")

	def test_page_count_matches_images(self):
		"""page_count matches the number of PDF417 images."""
		result = generate_barcode_page_data(_make_certificate_data())
		self.assertEqual(result["page_count"], len(result["pdf417_images"]))


if __name__ == "__main__":
	unittest.main()
