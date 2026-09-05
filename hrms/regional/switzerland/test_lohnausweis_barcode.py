# //// Neoffice — added file (no upstream equivalent): unit tests of the salary certificate barcode
# //// (annex 5).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Unit tests for the Swissdec salary certificate barcode (annex 5).

Pure unit tests — no database or Frappe context required.
Run with: python -m pytest hrms/regional/switzerland/test_lohnausweis_barcode.py -v
"""

import io
import unittest
import zipfile
import xml.etree.ElementTree as ET

from hrms.regional.switzerland.lohnausweis_barcode import (
	COMPRESSION_ZIP,
	CONTROL_VERSION,
	HEADER_SIZE,
	PDF417_COLUMNS,
	PDF417_SECURITY_LEVEL,
	TXAB_NS,
	ZIP_ENTRY_NAME,
	build_certificate_identifier,
	build_txab_zip,
	generate_barcode_page_data,
	generate_txab_xml,
	parse_symbol_header,
	split_into_symbols,
)

NS = {"t": TXAB_NS}


def _make_certificate_data(**overrides):
	"""Build a complete certificate_data dict for tests."""
	data = {
		"employer": {
			"name": "AlpInnovate Sàrl",
			"address": "Rue du Test 1\n1000 Lausanne",
			"uid_bfs": "CHE-123.456.789",
			"zip_code": "1000",
			"city": "Lausanne",
		},
		"employee": {
			"name": "Jean Claude",
			"first_name": "Jean",
			"last_name": "Claude",
			"zip_code": "1004",
			"city": "Lausanne",
			"avs_number": "756.1234.5678.97",
			"date_of_birth": "1985-04-12",
			"date_of_joining": "2020-02-01",
			"relieving_date": "",
		},
		"fiscal_year": "2025",
		"posting_date": "2026-01-15",
		"certificate_id": "CH-CERT-2025-Jean Claude",
		"free_transport": False,
		"lunch_checks": False,
		"descriptions": {},
		"positions": {
			"1": 96000.0,
			"2.1": 0, "2.2": 0, "2.3": 0,
			"3": 8000.0, "4": 0, "5": 0, "6": 0, "7": 0,
			"8": 104000.0,
			"9": 6640.0, "10.1": 3600.0, "10.2": 0,
			"11": 93760.0,
			"12": 0,
			"13.1.1": 0, "13.1.2": 0, "13.2.1": 0, "13.2.2": 0, "13.2.3": 0, "13.3": 0,
			"14": 0,
			"15": "Généré automatiquement.",
		},
	}
	data.update(overrides)
	return data


def _parse(xml_bytes):
	return ET.fromstring(xml_bytes)


# ===========================================================================
# TxAB XML tests
# ===========================================================================
class TestTxabXml(unittest.TestCase):
	def test_root_element_and_namespace(self):
		root = _parse(generate_txab_xml(_make_certificate_data()))
		self.assertEqual(root.tag, f"{{{TXAB_NS}}}T")
		# SysV/SID are limited to 3 chars; SID "0" until Swissdec assigns
		# Neoffice a SystemID at certification.
		self.assertEqual(root.get("SysV"), "5.0")
		self.assertEqual(root.get("SID"), "0")

	def test_person_identity_attributes(self):
		root = _parse(generate_txab_xml(_make_certificate_data()))
		person = root.find("t:PersonID", NS)
		self.assertEqual(person.get("Lastname"), "Claude")
		self.assertEqual(person.get("Firstname"), "Jean")
		self.assertEqual(person.get("ZIP"), "1004")
		self.assertEqual(person.get("City"), "Lausanne")

	def test_person_name_split_fallback(self):
		"""Without explicit first/last name, the full name is split."""
		data = _make_certificate_data()
		data["employee"].pop("first_name")
		data["employee"].pop("last_name")
		data["employee"]["name"] = "Marie Anne Dupont"
		root = _parse(generate_txab_xml(data))
		person = root.find("t:PersonID", NS)
		self.assertEqual(person.get("Firstname"), "Marie")
		self.assertEqual(person.get("Lastname"), "Anne Dupont")

	def test_company_attributes(self):
		root = _parse(generate_txab_xml(_make_certificate_data()))
		company = root.find("t:Company", NS)
		self.assertIsNotNone(company)
		self.assertEqual(company.get("UID-BFS"), "CHE-123.456.789")
		self.assertEqual(company.get("HR-RC-Name"), "AlpInnovate Sàrl")
		self.assertEqual(company.get("ZIP"), "1000")
		self.assertEqual(company.get("City"), "Lausanne")
		self.assertEqual(company.get("Street"), "Rue du Test 1")

	def test_person_id_avs_number_dotted(self):
		"""SV-AS-Nr must keep the official dotted format."""
		root = _parse(generate_txab_xml(_make_certificate_data()))
		avs = root.find("t:PersonID/t:SV-AS-Nr", NS)
		self.assertIsNotNone(avs)
		self.assertEqual(avs.text, "756.1234.5678.97")

	def test_person_id_falls_back_to_birthdate(self):
		"""Without a valid AVS number, DateOfBirth identifies the person."""
		data = _make_certificate_data()
		data["employee"]["avs_number"] = ""
		root = _parse(generate_txab_xml(data))
		self.assertIsNone(root.find("t:PersonID/t:SV-AS-Nr", NS))
		dob = root.find("t:PersonID/t:DateOfBirth", NS)
		self.assertEqual(dob.text, "1985-04-12")

	def test_person_id_unknown_as_last_resort(self):
		data = _make_certificate_data()
		data["employee"]["avs_number"] = ""
		data["employee"]["date_of_birth"] = ""
		root = _parse(generate_txab_xml(data))
		self.assertIsNotNone(root.find("t:PersonID/t:unknown", NS))

	def test_avs_number_normalized_to_dots(self):
		"""An AVS number without separators is reformatted with dots."""
		data = _make_certificate_data()
		data["employee"]["avs_number"] = "7561234567897"
		root = _parse(generate_txab_xml(data))
		self.assertEqual(root.find("t:PersonID/t:SV-AS-Nr", NS).text, "756.1234.5678.97")

	def test_salary_section_period(self):
		root = _parse(generate_txab_xml(_make_certificate_data()))
		self.assertEqual(root.find("t:S/t:Period/t:from", NS).text, "2025-01-01")
		self.assertEqual(root.find("t:S/t:Period/t:until", NS).text, "2025-12-31")

	def test_period_bounded_by_entry_and_exit(self):
		data = _make_certificate_data()
		data["employee"]["date_of_joining"] = "2025-03-15"
		data["employee"]["relieving_date"] = "2025-10-31"
		root = _parse(generate_txab_xml(data))
		self.assertEqual(root.find("t:S/t:Period/t:from", NS).text, "2025-03-15")
		self.assertEqual(root.find("t:S/t:Period/t:until", NS).text, "2025-10-31")

	def test_amount_format_two_decimals(self):
		root = _parse(generate_txab_xml(_make_certificate_data()))
		self.assertEqual(root.find("t:S/t:Income", NS).text, "96000.00")
		self.assertEqual(root.find("t:S/t:GrossIncome", NS).text, "104000.00")
		self.assertEqual(root.find("t:S/t:NetIncome", NS).text, "93760.00")

	def test_gross_and_net_always_present(self):
		"""GrossIncome and NetIncome are required by the schema, even at 0."""
		data = _make_certificate_data()
		data["positions"] = {"15": ""}
		root = _parse(generate_txab_xml(data))
		self.assertEqual(root.find("t:S/t:GrossIncome", NS).text, "0.00")
		self.assertEqual(root.find("t:S/t:NetIncome", NS).text, "0.00")

	def test_zero_optional_positions_omitted(self):
		root = _parse(generate_txab_xml(_make_certificate_data()))
		self.assertIsNone(root.find("t:S/t:DeductionAtSource", NS))
		self.assertIsNone(root.find("t:S/t:Charges", NS))
		self.assertIsNone(root.find("t:S/t:FringeBenefits", NS))

	def test_sporadic_benefits_sort_sum(self):
		"""Position 3 renders as SortSumType with mandatory text."""
		data = _make_certificate_data()
		data["descriptions"] = {"3": "Bonus annuel"}
		root = _parse(generate_txab_xml(data))
		sporadic = root.find("t:S/t:SporadicBenefits", NS)
		self.assertEqual(sporadic.find("t:Text", NS).text, "Bonus annuel")
		self.assertEqual(sporadic.find("t:Sum", NS).text, "8000.00")

	def test_fringe_benefits_mapping(self):
		"""2.1 → FoodLodging, 2.2 → CompanyCar, 2.3 → Other (form semantics)."""
		data = _make_certificate_data()
		data["positions"].update({"2.1": 6600.0, "2.2": 4320.0, "2.3": 500.0})
		data["descriptions"] = {"2.3": "Abonnement fitness"}
		root = _parse(generate_txab_xml(data))
		fringe = root.find("t:S/t:FringeBenefits", NS)
		self.assertEqual(fringe.find("t:FoodLodging", NS).text, "6600.00")
		self.assertEqual(fringe.find("t:CompanyCar", NS).text, "4320.00")
		self.assertEqual(fringe.find("t:Other/t:Text", NS).text, "Abonnement fitness")
		self.assertEqual(fringe.find("t:Other/t:Sum", NS).text, "500.00")

	def test_bvg_contribution_regular_and_purchase(self):
		data = _make_certificate_data()
		data["positions"]["10.2"] = 12000.0
		root = _parse(generate_txab_xml(data))
		bvg = root.find("t:S/t:BVG-LPP-Contribution", NS)
		self.assertEqual(bvg.find("t:Regular", NS).text, "3600.00")
		self.assertEqual(bvg.find("t:Purchase", NS).text, "12000.00")

	def test_social_contribution_element_name(self):
		root = _parse(generate_txab_xml(_make_certificate_data()))
		el = root.find("t:S/t:AHV-ALV-NBUV-AVS-AC-AANP-Contribution", NS)
		self.assertEqual(el.text, "6640.00")

	def test_charges_structure(self):
		"""13.x expenses map to Charges/Effective, LumpSum and Education."""
		data = _make_certificate_data()
		data["positions"].update(
			{"13.1.1": 1200.0, "13.1.2": 300.0, "13.2.1": 3600.0, "13.2.2": 2400.0, "13.2.3": 150.0, "13.3": 2000.0}
		)
		root = _parse(generate_txab_xml(data))
		charges = root.find("t:S/t:Charges", NS)
		self.assertEqual(charges.find("t:Effective/t:TravelFoodAccommodation", NS).text, "1200.00")
		self.assertEqual(charges.find("t:Effective/t:Other/t:Sum", NS).text, "300.00")
		self.assertEqual(charges.find("t:LumpSum/t:Representation", NS).text, "3600.00")
		self.assertEqual(charges.find("t:LumpSum/t:Car", NS).text, "2400.00")
		self.assertEqual(charges.find("t:LumpSum/t:Other/t:Sum", NS).text, "150.00")
		self.assertEqual(charges.find("t:Education", NS).text, "2000.00")

	def test_boxes_f_and_g(self):
		data = _make_certificate_data(free_transport=True, lunch_checks=True)
		root = _parse(generate_txab_xml(data))
		self.assertIsNotNone(root.find("t:S/t:FreeTransport", NS))
		self.assertIsNotNone(root.find("t:S/t:CanteenLunchCheck", NS))

	def test_remark(self):
		root = _parse(generate_txab_xml(_make_certificate_data()))
		self.assertEqual(root.find("t:S/t:Remark", NS).text, "Généré automatiquement.")

	def test_doc_id(self):
		root = _parse(generate_txab_xml(_make_certificate_data()))
		self.assertEqual(root.find("t:S/t:DocID", NS).text, "CH-CERT-2025-Jean Claude")


# ===========================================================================
# ZIP container tests
# ===========================================================================
class TestTxabZip(unittest.TestCase):
	def test_zip_entry_named_txab(self):
		"""Annex 5: Info-ZIP archive with a single entry named 'txab'."""
		zip_bytes = build_txab_zip(b"<T/>")
		with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
			self.assertEqual(zf.namelist(), [ZIP_ENTRY_NAME])

	def test_zip_roundtrip(self):
		xml = generate_txab_xml(_make_certificate_data())
		zip_bytes = build_txab_zip(xml)
		with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
			self.assertEqual(zf.read(ZIP_ENTRY_NAME), xml)

	def test_zip_magic_bytes(self):
		"""A real ZIP archive starts with the PK signature (not raw zlib)."""
		zip_bytes = build_txab_zip(b"data")
		self.assertEqual(zip_bytes[:2], b"PK")


# ===========================================================================
# Control header tests
# ===========================================================================
class TestControlHeader(unittest.TestCase):
	def test_single_symbol_header(self):
		symbols = split_into_symbols(b"x" * 100, identification=b"ABCD")
		self.assertEqual(len(symbols), 1)
		h = parse_symbol_header(symbols[0])
		self.assertEqual(h["identification"], b"ABCD")
		self.assertEqual(h["compression"], "z")
		self.assertEqual(h["size"], HEADER_SIZE + 100)
		self.assertEqual(h["page_marker"], 1)
		self.assertEqual(h["control_version"], CONTROL_VERSION)
		self.assertEqual(h["symbol_number"], 1)
		self.assertEqual(h["symbol_count"], 1)
		self.assertEqual(h["payload"], b"x" * 100)

	def test_multi_symbol_split(self):
		data = bytes(range(256)) * 10  # 2560 bytes
		symbols = split_into_symbols(data, identification=b"WXYZ", max_payload=550)
		self.assertEqual(len(symbols), 5)
		headers = [parse_symbol_header(s) for s in symbols]
		# Identification shared by all symbols
		self.assertEqual({h["identification"] for h in headers}, {b"WXYZ"})
		# First page marked 1, following pages 2
		self.assertEqual([h["page_marker"] for h in headers], [1, 2, 2, 2, 2])
		# Numbering and total
		self.assertEqual([h["symbol_number"] for h in headers], [1, 2, 3, 4, 5])
		self.assertEqual({h["symbol_count"] for h in headers}, {5})
		# Payload reassembles to the original data
		self.assertEqual(b"".join(h["payload"] for h in headers), data)

	def test_symbol_size_field(self):
		symbols = split_into_symbols(b"y" * 2500, identification=b"IDID", max_payload=550)
		sizes = [parse_symbol_header(s)["size"] for s in symbols]
		self.assertEqual(sizes, [564, 564, 564, 564, 314])

	def test_random_identification_by_default(self):
		s1 = split_into_symbols(b"data")
		s2 = split_into_symbols(b"data")
		# 4 random bytes: virtually always different between two calls
		self.assertEqual(len(parse_symbol_header(s1[0])["identification"]), 4)

	def test_identification_must_be_4_bytes(self):
		with self.assertRaises(ValueError):
			split_into_symbols(b"data", identification=b"TOOLONG")

	def test_max_99_symbols(self):
		with self.assertRaises(ValueError):
			split_into_symbols(b"z" * 1000, max_payload=10)  # would need 100

	def test_header_is_14_bytes(self):
		symbols = split_into_symbols(b"q" * 10, identification=b"HHHH")
		self.assertEqual(len(symbols[0]), HEADER_SIZE + 10)
		self.assertEqual(symbols[0][4], COMPRESSION_ZIP)


# ===========================================================================
# Identifier tests (CODE128, internal)
# ===========================================================================
class TestCertificateIdentifier(unittest.TestCase):
	def test_basic_identifier(self):
		ident = build_certificate_identifier("CHE-123.456.789", "756.1234.5678.97", "2025")
		self.assertEqual(len(ident), 16)
		self.assertEqual(ident, "4567895678972025")

	def test_short_inputs_padded(self):
		ident = build_certificate_identifier("12", "34", "25")
		self.assertEqual(ident, "0000120000340025")

	def test_empty_inputs(self):
		ident = build_certificate_identifier("", "", "")
		self.assertEqual(ident, "0000000000000000")


# ===========================================================================
# End-to-end pipeline tests
# ===========================================================================
class TestGenerateBarcodePageData(unittest.TestCase):
	def test_full_pipeline(self):
		result = generate_barcode_page_data(_make_certificate_data())
		self.assertEqual(result["page_count"], len(result["pdf417_images"]))
		self.assertGreaterEqual(result["page_count"], 1)
		self.assertTrue(result["identifier"].isdigit())
		self.assertIn("<T", result["xml_preview"])
		self.assertIn(TXAB_NS, result["xml_preview"])
		# base64 sanity
		import base64

		png = base64.b64decode(result["pdf417_images"][0])
		self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")

	def test_pdf417_parameters(self):
		"""Annex 5: error correction level 2 (reference implementation: 15 columns)."""
		self.assertEqual(PDF417_SECURITY_LEVEL, 2)
		self.assertEqual(PDF417_COLUMNS, 15)

	def test_symbol_decodes_back_to_certificate(self):
		"""Reassembling the symbol payloads yields the txab ZIP and XML."""
		data = _make_certificate_data()
		xml = generate_txab_xml(data)
		zip_bytes = build_txab_zip(xml)
		symbols = split_into_symbols(zip_bytes, identification=b"TEST")
		payload = b"".join(parse_symbol_header(s)["payload"] for s in symbols)
		with zipfile.ZipFile(io.BytesIO(payload)) as zf:
			recovered = zf.read(ZIP_ENTRY_NAME)
		self.assertEqual(recovered, xml)


if __name__ == "__main__":
	unittest.main()
