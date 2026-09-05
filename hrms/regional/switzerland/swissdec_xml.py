# //// Neoffice — added file (no upstream equivalent): Swissdec ELM SalaryDeclaration XML builder.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Swissdec ELM 5.0 XML generation engine.

Generates SalaryDeclaration XML conforming to the Swissdec ELM standard.
The generated XML can be imported into certified transmitters (SwissDecTX, etc.).

Reference namespace: http://www.swissdec.ch/schema/sd/20050902/SalaryDeclaration
"""

from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from frappe.utils import flt, formatdate, getdate

from hrms.regional.switzerland.constants import SWISS_CANTONS

# ELM 5.0 namespace
SWISSDEC_NS = "http://www.swissdec.ch/schema/sd/20050902/SalaryDeclaration"
SCHEMA_VERSION = "5.0"

# Permit type mapping to ELM codes
PERMIT_MAP = {
	"Swiss Citizen": "01",
	"Permit C (Settlement)": "02",
	"Permit B (Residence)": "03",
	"Permit G (Cross-border)": "05",
	"Permit L (Short-term)": "04",
}


def generate_salary_declaration(
	company_data, employees_data, config, fiscal_year,
	declaration_type="Year-End", declaration_month=None, institutions=None,
	completeness_flags=None,
):
	"""Main entry point: generate full SalaryDeclaration XML.

	Args:
		company_data: dict with company document fields.
		employees_data: list of dicts with employee_doc and salary_data keys.
		config: Swiss Social Insurance Config dict.
		fiscal_year: Fiscal Year name string.
		declaration_type: "Year-End", "Monthly", or "Correction".
		declaration_month: Month number (1-12) for Monthly declarations.
		institutions: dict of institution flags (include_avs, include_ac, etc.).
		completeness_flags: dict with laa_complete, ijm_complete, lpp_complete bools.

	Returns:
		bytes: UTF-8 encoded XML content.
	"""
	if institutions is None:
		institutions = _default_institutions()
	if completeness_flags is None:
		completeness_flags = {}

	root = Element("SalaryDeclaration")
	root.set("xmlns", SWISSDEC_NS)
	root.set("schemaVersion", SCHEMA_VERSION)

	# Company element
	company_el = _build_company_element(root, company_data, config, fiscal_year)

	# Staff element with all employees
	staff_el = SubElement(company_el, "Staff")

	for emp_data in employees_data:
		emp_doc = emp_data["employee_doc"]
		salary_data = emp_data["salary_data"]

		if not salary_data or not salary_data.get("months_worked"):
			continue

		_build_person_element(staff_el, emp_doc, salary_data, config, institutions, completeness_flags)

	return _prettify_xml(root)


def _build_company_element(root, company_data, config, fiscal_year):
	"""Build the <Company> element with employer identification and address.

	Args:
		root: Parent XML element.
		company_data: dict with company fields.
		config: Swiss Social Insurance Config dict.
		fiscal_year: Fiscal Year name.

	Returns:
		Company Element.
	"""
	company_el = SubElement(root, "Company")

	# Company identification
	uid = company_data.get("ch_uid_bfs") or ""
	if uid:
		uid_el = SubElement(company_el, "UID-BFS")
		_set_text(uid_el, uid.replace("-", "").replace(".", "").replace(" ", ""))

	name_el = SubElement(company_el, "Name")
	_set_text(name_el, company_data.get("company_name") or "")

	# Address
	address_el = SubElement(company_el, "Address")
	# Try to get address fields from company
	street = company_data.get("address_line1") or company_data.get("address") or ""
	zip_code = company_data.get("pincode") or ""
	city = company_data.get("city") or ""

	if street:
		_add_text_element(address_el, "Street", street)
	if zip_code:
		_add_text_element(address_el, "ZIP-Code", zip_code)
	if city:
		_add_text_element(address_el, "City", city)

	_add_text_element(address_el, "Country", "CH")

	# Contact
	contact_person = company_data.get("ch_contact_person") or ""
	contact_phone = company_data.get("ch_contact_phone") or ""
	contact_email = company_data.get("ch_contact_email") or ""

	if contact_person or contact_phone or contact_email:
		contact_el = SubElement(company_el, "Contact")
		if contact_person:
			_add_text_element(contact_el, "Name", contact_person)
		if contact_phone:
			_add_text_element(contact_el, "PhoneNumber", contact_phone)
		if contact_email:
			_add_text_element(contact_el, "Email", contact_email)

	# Fiscal year
	_add_text_element(company_el, "AccountingPeriod", fiscal_year)

	return company_el


def _build_person_element(staff_el, employee_doc, salary_data, config, institutions,
	completeness_flags=None):
	"""Build a <Person> element for a single employee.

	Args:
		staff_el: Parent <Staff> element.
		employee_doc: Employee document dict-like.
		salary_data: Annual salary summary dict.
		config: Swiss Social Insurance Config dict.
		institutions: dict of institution inclusion flags.
		completeness_flags: dict with laa_complete, ijm_complete, lpp_complete bools.
	"""
	if completeness_flags is None:
		completeness_flags = {}

	person_el = SubElement(staff_el, "Person")

	# Particulars (identification)
	_build_particulars(person_el, employee_doc)

	# Activity (work details)
	_build_activity(person_el, employee_doc, salary_data)

	# Institution-specific salary declarations
	if institutions.get("include_avs"):
		_build_avs_salary(person_el, salary_data, employee_doc, config)

	if institutions.get("include_ac"):
		_build_ac_salary(person_el, salary_data, employee_doc, config)

	if institutions.get("include_lpp"):
		lpp_complete = completeness_flags.get("lpp_complete", True)
		_build_lpp_salary(person_el, salary_data, employee_doc, config, is_complete=lpp_complete)

	if institutions.get("include_laa"):
		laa_complete = completeness_flags.get("laa_complete", True)
		_build_laa_salary(person_el, salary_data, employee_doc, config, is_complete=laa_complete)

	if institutions.get("include_ijm"):
		ijm_complete = completeness_flags.get("ijm_complete", True)
		_build_ijm_salary(person_el, salary_data, employee_doc, config, is_complete=ijm_complete)

	if institutions.get("include_qst") and employee_doc.get("ch_qst_subject"):
		_build_qst_salary(person_el, salary_data, employee_doc, config)

	if institutions.get("include_fak"):
		_build_fak_salary(person_el, salary_data, employee_doc, config)


def _build_particulars(person_el, employee_doc):
	"""Build <Particulars> with personal identification data."""
	part_el = SubElement(person_el, "Particulars")

	# AVS number
	avs = employee_doc.get("ch_avs_number") or ""
	if avs:
		_add_text_element(part_el, "SV-AS-Number", avs.replace(".", ""))

	# Name
	first_name = employee_doc.get("first_name") or ""
	last_name = employee_doc.get("last_name") or ""
	_add_text_element(part_el, "Firstname", first_name)
	_add_text_element(part_el, "Lastname", last_name)

	# Date of birth
	dob = employee_doc.get("date_of_birth")
	if dob:
		_add_text_element(part_el, "DateOfBirth", _format_date(dob))

	# Gender
	gender = employee_doc.get("gender") or ""
	if gender:
		gender_code = "1" if gender == "Male" else "2"
		_add_text_element(part_el, "Sex", gender_code)

	# Nationality
	nationality = employee_doc.get("ch_nationality") or ""
	if nationality:
		_add_text_element(part_el, "Nationality", nationality)

	# Marital status
	marital = employee_doc.get("marital_status") or ""
	if marital:
		status_map = {
			"Single": "1",
			"Married": "2",
			"Divorced": "4",
			"Widowed": "5",
		}
		code = status_map.get(marital)
		if code:
			_add_text_element(part_el, "MaritalStatus", code)


def _build_activity(person_el, employee_doc, salary_data):
	"""Build <Activity> with work location and employment details."""
	act_el = SubElement(person_el, "Activity")

	# Work canton
	canton = employee_doc.get("ch_fiscal_canton") or ""
	if canton:
		_add_text_element(act_el, "WorkplaceCanton", canton)

	# Permit type
	permit = employee_doc.get("ch_permit_type") or ""
	permit_code = PERMIT_MAP.get(permit, "")
	if permit_code:
		_add_text_element(act_el, "CategoryOfResidencePermit", permit_code)

	# Entry date
	entry = employee_doc.get("ch_entry_date") or employee_doc.get("date_of_joining")
	if entry:
		_add_text_element(act_el, "EntryDate", _format_date(entry))

	# Exit date
	exit_date = employee_doc.get("ch_exit_date") or employee_doc.get("relieving_date")
	if exit_date:
		_add_text_element(act_el, "WithdrawalDate", _format_date(exit_date))

	# Work percentage
	work_pct = flt(employee_doc.get("ch_work_percentage") or 100)
	_add_text_element(act_el, "ActivityRate", str(round(work_pct, 1)))

	# Period
	period_start = salary_data.get("period_start")
	period_end = salary_data.get("period_end")
	if period_start:
		_add_text_element(act_el, "PeriodFrom", _format_date(period_start))
	if period_end:
		_add_text_element(act_el, "PeriodTo", _format_date(period_end))


def _build_avs_salary(person_el, salary_data, employee_doc, config):
	"""Build <AHV-AVS-Salaries> element for AVS/AI/APG declaration."""
	avs_el = SubElement(person_el, "AHV-AVS-Salaries")

	avs_salary = flt(salary_data.get("avs_salary"))
	_add_amount_element(avs_el, "AHV-AVS-Income", avs_salary)
	_add_amount_element(avs_el, "ALV-AC-Income", flt(salary_data.get("ac_salary")))

	# Contributions
	_add_amount_element(avs_el, "AHV-AVS-EE", flt(salary_data.get("avs_employee")))
	_add_amount_element(avs_el, "AHV-AVS-ER", flt(salary_data.get("avs_employer")))

	return avs_el


def _build_ac_salary(person_el, salary_data, employee_doc, config):
	"""Build <ALV-AC-Salaries> element for AC/ALV declaration."""
	ac_el = SubElement(person_el, "ALV-AC-Salaries")

	_add_amount_element(ac_el, "ALV-AC-Income", flt(salary_data.get("ac_salary")))
	_add_amount_element(ac_el, "ALV-AC-EE", flt(salary_data.get("ac_employee")))
	_add_amount_element(ac_el, "ALV-AC-ER", flt(salary_data.get("ac_employer")))

	# Solidarity
	sol_ee = flt(salary_data.get("ac_solidarity_employee"))
	sol_er = flt(salary_data.get("ac_solidarity_employer"))
	if sol_ee or sol_er:
		_add_amount_element(ac_el, "ALV-AC-SolidarityPercent-EE", sol_ee)
		_add_amount_element(ac_el, "ALV-AC-SolidarityPercent-ER", sol_er)

	return ac_el


def _build_lpp_salary(person_el, salary_data, employee_doc, config, is_complete=True):
	"""Build <BVG-LPP-Salaries> element for LPP/BVG declaration."""
	lpp_el = SubElement(person_el, "BVG-LPP-Salaries")
	lpp_el.set("complete", "true" if is_complete else "false")

	_add_amount_element(lpp_el, "BVG-LPP-AnnualSalary", flt(salary_data.get("total_gross")))
	_add_amount_element(lpp_el, "BVG-LPP-CoordinatedSalary", flt(salary_data.get("lpp_coordinated")))
	_add_amount_element(lpp_el, "BVG-LPP-EE", flt(salary_data.get("lpp_employee")))
	_add_amount_element(lpp_el, "BVG-LPP-ER", flt(salary_data.get("lpp_employer")))

	return lpp_el


def _build_laa_salary(person_el, salary_data, employee_doc, config, is_complete=True):
	"""Build <UVG-LAA-Salaries> element for LAA/UVG declaration."""
	laa_el = SubElement(person_el, "UVG-LAA-Salaries")
	laa_el.set("complete", "true" if is_complete else "false")

	_add_amount_element(laa_el, "UVG-LAA-Income", flt(salary_data.get("laa_salary")))
	_add_amount_element(laa_el, "UVG-LAA-BUV-ER", flt(salary_data.get("laa_professional")))
	_add_amount_element(laa_el, "UVG-LAA-NBUV-EE", flt(salary_data.get("laa_nonprofessional")))

	return laa_el


def _build_ijm_salary(person_el, salary_data, employee_doc, config, is_complete=True):
	"""Build <KTG-IJM-Salaries> element for IJM/KTG declaration."""
	ijm_el = SubElement(person_el, "KTG-IJM-Salaries")
	ijm_el.set("complete", "true" if is_complete else "false")

	# IJM insured salary = same base as gross (insurer-specific cap may apply)
	_add_amount_element(ijm_el, "KTG-IJM-Income", flt(salary_data.get("total_gross")))
	_add_amount_element(ijm_el, "KTG-IJM-EE", flt(salary_data.get("ijm_employee")))
	_add_amount_element(ijm_el, "KTG-IJM-ER", flt(salary_data.get("ijm_employer")))

	return ijm_el


def _build_qst_salary(person_el, salary_data, employee_doc, config):
	"""Build <QST-Salaries> element for source tax declaration."""
	qst_el = SubElement(person_el, "QST-Salaries")

	# Canton
	canton = (
		employee_doc.get("ch_qst_taxation_canton")
		or employee_doc.get("ch_fiscal_canton")
		or ""
	)
	if canton:
		_add_text_element(qst_el, "Canton", canton)

	# Tariff code
	tariff_code = employee_doc.get("ch_qst_tariff_code") or ""
	if tariff_code:
		_add_text_element(qst_el, "TariffCode", tariff_code)

	# Gross and tax
	_add_amount_element(qst_el, "QST-GrossIncome", flt(salary_data.get("total_gross")))
	_add_amount_element(qst_el, "QST-Tax", flt(salary_data.get("source_tax_total")))

	# Cross-border info
	if employee_doc.get("ch_is_cross_border"):
		cb_el = SubElement(qst_el, "CrossBorder")
		country = employee_doc.get("ch_residence_country") or ""
		if country:
			_add_text_element(cb_el, "ResidenceCountry", country)

	return qst_el


def _build_fak_salary(person_el, salary_data, employee_doc, config):
	"""Build <FAK-CAF-Salaries> element for Family Allowances declaration."""
	fak_el = SubElement(person_el, "FAK-CAF-Salaries")

	_add_amount_element(fak_el, "FAK-CAF-Income", flt(salary_data.get("total_gross")))
	_add_amount_element(fak_el, "FAK-CAF-ER", flt(salary_data.get("fak_employer")))

	return fak_el


# --- XML Helper Functions ---


def _add_text_element(parent, tag, text):
	"""Add a child element with text content."""
	el = SubElement(parent, tag)
	el.text = str(text) if text is not None else ""
	return el


def _add_amount_element(parent, tag, amount):
	"""Add a child element with a formatted currency amount."""
	el = SubElement(parent, tag)
	el.text = f"{flt(amount):.2f}"
	return el


def _set_text(element, text):
	"""Set text on an element."""
	element.text = str(text) if text is not None else ""


def _format_date(date_val):
	"""Format a date value to ISO format (YYYY-MM-DD)."""
	if not date_val:
		return ""
	d = getdate(date_val)
	return d.strftime("%Y-%m-%d")


def _prettify_xml(element):
	"""Convert an Element to pretty-printed UTF-8 bytes.

	Args:
		element: Root Element.

	Returns:
		bytes: UTF-8 encoded XML with XML declaration.
	"""
	rough_string = tostring(element, encoding="unicode")
	reparsed = minidom.parseString(rough_string)
	return reparsed.toprettyxml(indent="  ", encoding="UTF-8")


def _default_institutions():
	"""Return default institution inclusion flags."""
	return {
		"include_avs": True,
		"include_ac": True,
		"include_lpp": True,
		"include_laa": True,
		"include_ijm": True,
		"include_qst": True,
		"include_fak": True,
		"include_ofs": False,
	}


# --- EMA (Eintritt/Mutation/Austritt) Notification XML ---


# EMA event type mapping to ELM codes
EMA_EVENT_MAP = {
	"Eintritt": "Entry",
	"Mutation": "Mutation",
	"Austritt": "Withdrawal",
}


def generate_ema_notification(
	company_data, employee_doc, event_type, event_date, institutions=None, config=None,
):
	"""Generate EMA notification XML for a single employee event.

	EMA notifications use the same SalaryDeclaration namespace but contain
	only the employee identification and the event details, addressed to
	specific institutions (AHV, FAK, BVG).

	Args:
		company_data: dict with company document fields.
		employee_doc: dict-like Employee document.
		event_type: "Eintritt", "Mutation", or "Austritt".
		event_date: Date of the event (str or date).
		institutions: dict with notify_avs, notify_fak, notify_bvg bools.
		config: Swiss Social Insurance Config dict.

	Returns:
		bytes: UTF-8 encoded XML content.
	"""
	if institutions is None:
		institutions = {"notify_avs": True, "notify_fak": True, "notify_bvg": True}
	if config is None:
		config = {}

	root = Element("SalaryDeclaration")
	root.set("xmlns", SWISSDEC_NS)
	root.set("schemaVersion", SCHEMA_VERSION)

	# Company element (reuse existing builder)
	company_el = _build_company_element(root, company_data, config, "")

	# EMA element
	ema_el = SubElement(company_el, "EMA")
	_add_text_element(ema_el, "EventType", EMA_EVENT_MAP.get(event_type, event_type))
	_add_text_element(ema_el, "EventDate", _format_date(event_date))

	# Target institutions
	targets_el = SubElement(ema_el, "Institutions")
	if institutions.get("notify_avs"):
		_add_text_element(targets_el, "AHV-AVS", "true")
	if institutions.get("notify_fak"):
		_add_text_element(targets_el, "FAK-CAF", "true")
	if institutions.get("notify_bvg"):
		_add_text_element(targets_el, "BVG-LPP", "true")

	# Person element (reuse existing builders for identification)
	person_el = SubElement(ema_el, "Person")
	_build_particulars(person_el, employee_doc)
	_build_activity(person_el, employee_doc, {"period_start": None, "period_end": None})

	return _prettify_xml(root)
