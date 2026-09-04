#//// Neoffice — added file (no upstream equivalent): ISO 20022 pain.001.001.09 salary payment file
#//// (Swiss Payment Standard), generated straight from the submitted slips.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Salary payment file generation (ISO 20022 pain.001.001.09).

Generates the credit transfer initiation file for a monthly payroll cycle,
following the Swiss Payment Standard (SPS) implementation guidelines:
one PmtInf batch with category purpose SALA, one CdtTrfTxInf per submitted
salary slip, amounts from net_pay, creditor IBAN from Employee.bank_ac_no.

The debtor (employer) account comes from the Swiss Social Insurance Config
(payment_iban / payment_bic), with a fallback to the linked Account's
iban/bic custom fields when another app (e.g. erpnextswiss) provides them.

The file is self-contained on purpose: hrms must be able to produce salary
payment files without any other Swiss app installed. Transport (EBICS,
e-banking upload) stays out of scope — this module only builds the XML.
"""

import re
import xml.etree.ElementTree as ET
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from hrms.regional.switzerland.utils import get_swiss_social_insurance_config

PAIN_NAMESPACE = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"

# SWIFT/SPS restricted latin character set for pain.001 text fields
SWIFT_ALLOWED = re.compile(r"[^A-Za-z0-9/\-?:().,'+ ]")

# Minimal transliteration for common Swiss/European characters, applied
# before stripping — keeps names readable instead of dropping letters.
TRANSLITERATION = str.maketrans(
	{
		"ä": "a",
		"à": "a",
		"â": "a",
		"á": "a",
		"ã": "a",
		"å": "a",
		"ö": "o",
		"ô": "o",
		"ò": "o",
		"ó": "o",
		"õ": "o",
		"ø": "o",
		"ü": "u",
		"û": "u",
		"ù": "u",
		"ú": "u",
		"é": "e",
		"è": "e",
		"ê": "e",
		"ë": "e",
		"î": "i",
		"ï": "i",
		"ì": "i",
		"í": "i",
		"ç": "c",
		"ñ": "n",
		"ß": "ss",
		"Ä": "A",
		"À": "A",
		"Â": "A",
		"Á": "A",
		"Ã": "A",
		"Å": "A",
		"Ö": "O",
		"Ô": "O",
		"Ò": "O",
		"Ó": "O",
		"Õ": "O",
		"Ø": "O",
		"Ü": "U",
		"Û": "U",
		"Ù": "U",
		"Ú": "U",
		"É": "E",
		"È": "E",
		"Ê": "E",
		"Ë": "E",
		"Î": "I",
		"Ï": "I",
		"Ì": "I",
		"Í": "I",
		"Ç": "C",
		"Ñ": "N",
	}
)


def sanitize_swift_text(text, max_length=70):
	"""Reduce a string to the SWIFT character set accepted in pain.001 text fields."""
	if not text:
		return ""
	text = str(text).translate(TRANSLITERATION)
	text = SWIFT_ALLOWED.sub(" ", text)
	# Collapse whitespace runs introduced by substitutions
	text = re.sub(r"\s+", " ", text).strip()
	return text[:max_length]


def clean_iban(iban):
	"""Normalize an IBAN: strip spaces, uppercase."""
	return (iban or "").replace(" ", "").upper()


def validate_iban(iban):
	"""Check an IBAN with the ISO 13616 mod-97 checksum. Returns True/False."""
	iban = clean_iban(iban)
	if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{1,30}", iban):
		return False
	# Move the first 4 chars to the end, convert letters to numbers (A=10 ... Z=35)
	rearranged = iban[4:] + iban[:4]
	digits = "".join(str(int(ch, 36)) for ch in rearranged)
	return int(digits) % 97 == 1


def split_swiss_address(address_text):
	"""Split a two-line postal address into structured pain.001 fields.

	Expected layout (same convention as the Employee.permanent_address
	usage elsewhere in Swiss payroll): line 1 = street + house number,
	line 2 = postcode + town.

	Returns a dict with street, building, pincode, city — values may be
	empty strings when the information cannot be derived.
	"""
	result = {"street": "", "building": "", "pincode": "", "city": ""}
	if not address_text:
		return result

	lines = [line.strip() for line in str(address_text).splitlines() if line.strip()]
	if lines:
		# Trailing token counts as the house number when it starts with a digit
		parts = lines[0].rsplit(" ", 1)
		if len(parts) == 2 and parts[1][:1].isdigit():
			result["street"], result["building"] = parts[0], parts[1]
		else:
			result["street"] = lines[0]
	if len(lines) > 1:
		parts = lines[1].split(" ", 1)
		if parts[0][:1].isdigit():
			result["pincode"] = parts[0]
			result["city"] = parts[1] if len(parts) > 1 else ""
		else:
			result["city"] = lines[1]
	return result


def get_debtor_details(company, config=None):
	"""Resolve the employer-side (debtor) bank details for salary payments.

	Order: Swiss Social Insurance Config payment_iban/payment_bic, then the
	iban/bic custom fields on the linked payment Account when another app
	defines them. Raises when no valid IBAN can be found.
	"""
	config = config or get_swiss_social_insurance_config(company) or frappe._dict()

	iban = clean_iban(config.get("payment_iban"))
	bic = (config.get("payment_bic") or "").replace(" ", "").upper()
	account = config.get("payment_account")

	if (not iban or not bic) and account:
		# Fallback: Account.iban / Account.bic exist when erpnextswiss (or a
		# similar banking app) added them — reuse instead of double entry.
		account_meta = frappe.get_meta("Account")
		fieldnames = {df.fieldname for df in account_meta.fields}
		if not iban and "iban" in fieldnames:
			iban = clean_iban(frappe.db.get_value("Account", account, "iban"))
		if not bic and "bic" in fieldnames:
			bic = (frappe.db.get_value("Account", account, "bic") or "").replace(" ", "").upper()

	if not iban:
		frappe.throw(
			_(
				"No employer IBAN for salary payments. Set 'Payment IBAN' in the Swiss Social Insurance Config for {0}."
			).format(company)
		)
	if not validate_iban(iban):
		frappe.throw(_("Employer IBAN {0} is not a valid IBAN.").format(iban))
	if not bic:
		frappe.throw(
			_(
				"No BIC for the paying bank. Set 'Payment BIC' in the Swiss Social Insurance Config for {0}."
			).format(company)
		)

	# Company postal address (optional in the schema, recommended by SPS)
	address = {}
	address_name = frappe.db.get_value(
		"Dynamic Link",
		{"link_doctype": "Company", "link_name": company, "parenttype": "Address"},
		"parent",
	)
	if address_name:
		addr = frappe.db.get_value(
			"Address", address_name, ["address_line1", "pincode", "city", "country"], as_dict=True
		)
		if addr:
			address = split_swiss_address(addr.address_line1)
			address["pincode"] = addr.pincode or address.get("pincode") or ""
			address["city"] = addr.city or address.get("city") or ""
			address["country_code"] = (frappe.db.get_value("Country", addr.country, "code") or "ch").upper()

	return {"name": company, "iban": iban, "bic": bic, "address": address}


@frappe.whitelist()
def get_salary_payments(company, year, month):
	"""Preflight for the salary payment file of one payroll cycle.

	Lists the submitted salary slips of the month with the bank details
	needed for pain.001, and every blocking or non-blocking issue found.
	"""
	frappe.only_for(["HR Manager", "HR User", "System Manager"])
	year, month = int(year), int(month)
	start = date(year, month, 1)
	end = date(year, month, monthrange(year, month)[1])

	slips = frappe.get_all(
		"Salary Slip",
		filters={
			"company": company,
			"docstatus": 1,
			"start_date": ("between", [start, end]),
		},
		fields=["name", "employee", "employee_name", "net_pay", "end_date"],
		order_by="employee_name",
	)

	payments = []
	issues = []
	for slip in slips:
		emp = (
			frappe.db.get_value(
				"Employee",
				slip.employee,
				["bank_ac_no", "permanent_address"],
				as_dict=True,
			)
			or frappe._dict()
		)

		iban = clean_iban(emp.bank_ac_no)
		if slip.net_pay is None or slip.net_pay <= 0:
			issues.append(
				{
					"employee": slip.employee_name,
					"level": "error",
					"message": _("{0}: net pay is {1} — nothing to transfer").format(
						slip.employee_name, slip.net_pay
					),
				}
			)
			continue
		if not iban:
			issues.append(
				{
					"employee": slip.employee_name,
					"level": "error",
					"message": _("{0}: no IBAN on the employee (Bank Account No)").format(slip.employee_name),
				}
			)
			continue
		if not validate_iban(iban):
			issues.append(
				{
					"employee": slip.employee_name,
					"level": "error",
					"message": _("{0}: IBAN {1} fails the checksum").format(slip.employee_name, iban),
				}
			)
			continue
		if not emp.permanent_address:
			# Address is optional in pain.001 for domestic transfers — warn only
			issues.append(
				{
					"employee": slip.employee_name,
					"level": "warning",
					"message": _("{0}: no address on the employee (recommended in the payment file)").format(
						slip.employee_name
					),
				}
			)

		payments.append(
			{
				"salary_slip": slip.name,
				"employee": slip.employee,
				"employee_name": slip.employee_name,
				"iban": iban,
				"amount": slip.net_pay,
				"address": split_swiss_address(emp.permanent_address),
			}
		)

	debtor_error = None
	try:
		debtor = get_debtor_details(company)
	except frappe.ValidationError as e:
		debtor = None
		debtor_error = str(e)

	return {
		"payments": payments,
		"issues": issues,
		"debtor": debtor,
		"debtor_error": debtor_error,
		"total": float(sum(Decimal(str(p["amount"])) for p in payments)) if payments else 0.0,
	}


def _postal_address_element(parent, address, default_country="CH"):
	"""Append a PstlAdr element when structured address data is available."""
	if not address or not (address.get("street") or address.get("city")):
		return
	pstl = ET.SubElement(parent, "PstlAdr")
	if address.get("street"):
		ET.SubElement(pstl, "StrtNm").text = sanitize_swift_text(address["street"], 70)
	if address.get("building"):
		ET.SubElement(pstl, "BldgNb").text = sanitize_swift_text(address["building"], 16)
	if address.get("pincode"):
		ET.SubElement(pstl, "PstCd").text = sanitize_swift_text(address["pincode"], 16)
	if address.get("city"):
		ET.SubElement(pstl, "TwnNm").text = sanitize_swift_text(address["city"], 35)
	ET.SubElement(pstl, "Ctry").text = address.get("country_code") or default_country


def build_pain001(debtor, payments, execution_date, msg_id=None, remittance_text=None):
	"""Build the pain.001.001.09 XML document. Pure function, no DB access.

	Args:
		debtor: dict with name, iban, bic, address (from get_debtor_details).
		payments: list of dicts with salary_slip, employee_name, iban, amount, address.
		execution_date: requested execution date (date or string).
		msg_id: optional message id (defaults to a timestamped id).
		remittance_text: optional unstructured remittance line shown to the employee.

	Returns:
		XML string with declaration.
	"""
	if not payments:
		frappe.throw(_("No payments to include in the file."))

	now = datetime.now()
	msg_id = sanitize_swift_text(msg_id or f"HRMS-SALA-{now.strftime('%Y%m%d%H%M%S')}", 35)
	# SPS: the execution date must not be in the past
	execution_date = max(getdate(execution_date), getdate(nowdate()))

	amounts = [Decimal(str(p["amount"])).quantize(Decimal("0.01")) for p in payments]
	control_sum = sum(amounts)

	root = ET.Element("Document", xmlns=PAIN_NAMESPACE)
	cstmr = ET.SubElement(root, "CstmrCdtTrfInitn")

	grp = ET.SubElement(cstmr, "GrpHdr")
	ET.SubElement(grp, "MsgId").text = msg_id
	ET.SubElement(grp, "CreDtTm").text = now.strftime("%Y-%m-%dT%H:%M:%S")
	ET.SubElement(grp, "NbOfTxs").text = str(len(payments))
	ET.SubElement(grp, "CtrlSum").text = str(control_sum)
	initg = ET.SubElement(grp, "InitgPty")
	ET.SubElement(initg, "Nm").text = sanitize_swift_text(debtor["name"], 70)

	pmt = ET.SubElement(cstmr, "PmtInf")
	ET.SubElement(pmt, "PmtInfId").text = sanitize_swift_text(f"{msg_id}-P1", 35)
	ET.SubElement(pmt, "PmtMtd").text = "TRF"
	ET.SubElement(pmt, "BtchBookg").text = "true"
	pmt_tp = ET.SubElement(pmt, "PmtTpInf")
	ctgy = ET.SubElement(pmt_tp, "CtgyPurp")
	# SALA marks the batch as salary payments (bank statement confidentiality)
	ET.SubElement(ctgy, "Cd").text = "SALA"
	reqd = ET.SubElement(pmt, "ReqdExctnDt")
	ET.SubElement(reqd, "Dt").text = str(execution_date)

	dbtr = ET.SubElement(pmt, "Dbtr")
	ET.SubElement(dbtr, "Nm").text = sanitize_swift_text(debtor["name"], 70)
	_postal_address_element(dbtr, debtor.get("address"))
	dbtr_acct = ET.SubElement(pmt, "DbtrAcct")
	dbtr_acct_id = ET.SubElement(dbtr_acct, "Id")
	ET.SubElement(dbtr_acct_id, "IBAN").text = debtor["iban"]
	dbtr_agt = ET.SubElement(pmt, "DbtrAgt")
	fin = ET.SubElement(dbtr_agt, "FinInstnId")
	ET.SubElement(fin, "BICFI").text = debtor["bic"]

	for index, payment in enumerate(payments):
		tx = ET.SubElement(pmt, "CdtTrfTxInf")
		pmt_id = ET.SubElement(tx, "PmtId")
		ET.SubElement(pmt_id, "InstrId").text = sanitize_swift_text(f"{msg_id}-TX{index + 1}", 35)
		ET.SubElement(pmt_id, "EndToEndId").text = sanitize_swift_text(payment["salary_slip"], 35)
		amt = ET.SubElement(tx, "Amt")
		instd = ET.SubElement(amt, "InstdAmt", Ccy="CHF")
		instd.text = str(amounts[index])
		cdtr = ET.SubElement(tx, "Cdtr")
		ET.SubElement(cdtr, "Nm").text = sanitize_swift_text(payment["employee_name"], 70)
		_postal_address_element(cdtr, payment.get("address"))
		cdtr_acct = ET.SubElement(tx, "CdtrAcct")
		cdtr_acct_id = ET.SubElement(cdtr_acct, "Id")
		ET.SubElement(cdtr_acct_id, "IBAN").text = payment["iban"]
		if remittance_text:
			rmt = ET.SubElement(tx, "RmtInf")
			ET.SubElement(rmt, "Ustrd").text = sanitize_swift_text(remittance_text, 140)

	ET.indent(root, space="  ")
	return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def generate_pain001(company, year, month, execution_date=None):
	"""Collect the cycle's payments and build the pain.001 file content."""
	year, month = int(year), int(month)
	data = get_salary_payments(company, year, month)

	blocking = [i for i in data["issues"] if i["level"] == "error"]
	if blocking:
		frappe.throw(
			_("Cannot generate the payment file:")
			+ "<br>"
			+ "<br>".join(frappe.utils.escape_html(i["message"]) for i in blocking)
		)
	if data["debtor_error"]:
		frappe.throw(data["debtor_error"])
	if not data["payments"]:
		frappe.throw(_("No submitted salary slip found for {0}-{1}.").format(year, f"{month:02d}"))

	remittance = _("Salary {0}").format(f"{year}-{month:02d}")
	return build_pain001(
		debtor=data["debtor"],
		payments=data["payments"],
		execution_date=execution_date or nowdate(),
		remittance_text=remittance,
	)


@frappe.whitelist()
def download_pain001(company, year, month, execution_date=None):
	"""Download endpoint for the salary payment file of one cycle."""
	frappe.only_for(["HR Manager", "HR User", "System Manager"])
	content = generate_pain001(company, year, month, execution_date)
	frappe.response["filename"] = f"pain001-salaries-{frappe.scrub(company)}-{int(year)}-{int(month):02d}.xml"
	frappe.response["filecontent"] = content
	frappe.response["type"] = "binary"
