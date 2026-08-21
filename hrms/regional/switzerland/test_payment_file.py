# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import os
import unittest
import xml.etree.ElementTree as ET
from decimal import Decimal

from hrms.regional.switzerland.payment_file import (
	PAIN_NAMESPACE,
	build_pain001,
	clean_iban,
	sanitize_swift_text,
	split_swiss_address,
	validate_iban,
)

NS = {"p": PAIN_NAMESPACE}

DEBTOR = {
	"name": "AlpInnovate SA",
	"iban": "CH1680808123456789101",
	"bic": "RAIFCH22XXX",
	"address": {
		"street": "Rue de la Poste",
		"building": "17",
		"pincode": "1921",
		"city": "Matigny-Croix",
		"country_code": "CH",
	},
}

PAYMENTS = [
	{
		"salary_slip": "Sal Slip/Cyril Wizard/00002",
		"employee_name": "Cyril Wizard",
		"iban": "CH9300762011623852957",
		"amount": 5940.99,
		"address": {"street": "Rue du Test", "building": "1", "pincode": "8001", "city": "Zurich"},
	},
	{
		"salary_slip": "Sal Slip/Helie Copter/00007",
		"employee_name": "Hélie Cöpter",  # accents on purpose: must be transliterated
		"iban": "CH5604835012345678009",
		"amount": 5016.45,
		"address": {"street": "Chemin Essai", "building": "2", "pincode": "1003", "city": "Lausanne"},
	},
]


class TestIbanValidation(unittest.TestCase):
	def test_valid_ibans(self):
		for iban in (
			"CH93 0076 2011 6238 5295 7",
			"CH5604835012345678009",
			"DE89370400440532013000",
			"FR1420041010050500013M02606",
		):
			self.assertTrue(validate_iban(iban), iban)

	def test_invalid_ibans(self):
		for iban in (
			"CH93 0076 2011 6238 5295 8",  # wrong checksum
			"CH93",
			"",
			None,
			"XX00INVALID",
			"1234567890",
		):
			self.assertFalse(validate_iban(iban), str(iban))

	def test_clean_iban(self):
		self.assertEqual(clean_iban(" ch93 0076 2011 6238 5295 7 "), "CH9300762011623852957")


class TestSwiftSanitizer(unittest.TestCase):
	def test_transliteration(self):
		self.assertEqual(sanitize_swift_text("Müller & Söhne AG"), "Muller Sohne AG")
		self.assertEqual(sanitize_swift_text("Hélie Cöpter"), "Helie Copter")

	def test_length_cap(self):
		self.assertEqual(len(sanitize_swift_text("x" * 200, 35)), 35)

	def test_allowed_punctuation_kept(self):
		self.assertEqual(sanitize_swift_text("A-B/C(D).,'+?:"), "A-B/C(D).,'+?:")


class TestAddressSplit(unittest.TestCase):
	def test_two_lines(self):
		result = split_swiss_address("Rue du Test 1\n8001 Zurich")
		self.assertEqual(
			result, {"street": "Rue du Test", "building": "1", "pincode": "8001", "city": "Zurich"}
		)

	def test_house_number_with_letter(self):
		result = split_swiss_address("Bahnhofstrasse 12b\n8001 Zürich")
		self.assertEqual(result["building"], "12b")

	def test_street_without_number(self):
		result = split_swiss_address("Dorfplatz\n6060 Sarnen")
		self.assertEqual(result["street"], "Dorfplatz")
		self.assertEqual(result["building"], "")

	def test_empty(self):
		self.assertEqual(split_swiss_address(None)["street"], "")


class TestBuildPain001(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.xml = build_pain001(
			DEBTOR, PAYMENTS, execution_date="2099-01-25", remittance_text="Salaire 2026-08"
		)
		cls.root = ET.fromstring(cls.xml)

	def test_header_totals(self):
		grp = self.root.find(".//p:GrpHdr", NS)
		self.assertEqual(grp.find("p:NbOfTxs", NS).text, "2")
		self.assertEqual(Decimal(grp.find("p:CtrlSum", NS).text), Decimal("10957.44"))

	def test_salary_category_purpose(self):
		self.assertEqual(self.root.find(".//p:PmtTpInf/p:CtgyPurp/p:Cd", NS).text, "SALA")

	def test_debtor_block(self):
		self.assertEqual(self.root.find(".//p:DbtrAcct/p:Id/p:IBAN", NS).text, DEBTOR["iban"])
		self.assertEqual(self.root.find(".//p:DbtrAgt/p:FinInstnId/p:BICFI", NS).text, DEBTOR["bic"])

	def test_transactions(self):
		txs = self.root.findall(".//p:CdtTrfTxInf", NS)
		self.assertEqual(len(txs), 2)
		amounts = [tx.find("p:Amt/p:InstdAmt", NS) for tx in txs]
		self.assertEqual([a.text for a in amounts], ["5940.99", "5016.45"])
		self.assertTrue(all(a.get("Ccy") == "CHF" for a in amounts))
		ibans = [tx.find("p:CdtrAcct/p:Id/p:IBAN", NS).text for tx in txs]
		self.assertEqual(ibans, [p["iban"] for p in PAYMENTS])

	def test_accents_transliterated_in_output(self):
		self.assertNotIn("Cöpter", self.xml)
		self.assertIn("Helie Copter", self.xml)

	def test_creditor_address_structured(self):
		tx = self.root.find(".//p:CdtTrfTxInf", NS)
		adr = tx.find("p:Cdtr/p:PstlAdr", NS)
		self.assertEqual(adr.find("p:StrtNm", NS).text, "Rue du Test")
		self.assertEqual(adr.find("p:BldgNb", NS).text, "1")
		self.assertEqual(adr.find("p:PstCd", NS).text, "8001")
		self.assertEqual(adr.find("p:TwnNm", NS).text, "Zurich")
		self.assertEqual(adr.find("p:Ctry", NS).text, "CH")

	def test_remittance_info(self):
		self.assertEqual(self.root.find(".//p:RmtInf/p:Ustrd", NS).text, "Salaire 2026-08")

	def test_validates_against_swiss_xsd(self):
		"""Validate against the bundled Swiss Payment Standard schema (pain.001.001.09.ch.03)."""
		try:
			from lxml import etree as lxml_etree
		except ImportError:
			self.skipTest("lxml not available")
		xsd_path = os.path.join(os.path.dirname(__file__), "xsd", "pain.001.001.09.ch.03.xsd")
		schema = lxml_etree.XMLSchema(lxml_etree.parse(xsd_path))
		doc = lxml_etree.fromstring(self.xml.encode("utf-8"))
		self.assertTrue(schema.validate(doc), schema.error_log)
