# //// Neoffice — added file (no upstream equivalent): controller of the Swiss Salary Certificate
# //// (Lohnausweis / certificat de salaire, official Form 11) — a legal yearly document
# //// no upstream hrms doctype covers.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import re
import uuid

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, now_datetime

from hrms.regional.switzerland.constants import POSITION_FIELD_MAP
from hrms.regional.switzerland.salary_certificate import (
	DRAFT_DOC_ID,
	LANGUAGES,
	TEXT_ONLY_POSITIONS,
	build_remarks,
	certificate_language,
	certificate_positions,
	certificate_totals,
	employment_period,
	to_francs,
)
from hrms.regional.switzerland.utils import get_swiss_social_insurance_config

# Roles that see every certificate; anyone else only reads their own, once validated.
PAYROLL_STAFF_ROLES = ("HR Manager", "HR User")


class SwissSalaryCertificate(Document):
	def validate(self):
		self.validate_mandatory_fields()
		self.set_period()
		if self.language not in LANGUAGES:
			self.language = self._default_language()
		self.round_positions()
		self.calculate_totals()
		# //// Neoffice — box 15 is rebuilt from what the slips said (remark_facts, set when the
		# //// certificate is populated) and from the fields HR fills beside it, so it follows every
		# //// change. A certificate populated before 2026-09-23 has no facts: its text is kept.
		if self.docstatus == 0 and self.remark_facts:
			self.position_15_remarks = "\n".join(self._remarks())

	def before_insert(self):
		# An amended certificate is a rectification, a new document: neither validated nor sent
		# yet. The desk's Amend copies no_copy fields too (frappe.model.copy_doc, from_amend), so
		# the cancelled certificate's DocID and delivery would otherwise carry over.
		for field in ("doc_id", "finalized_on", "sent_to_employee_on", "sent_to"):
			self.set(field, None)

	def before_submit(self):
		# Swissdec guidelines 6.0, 9.1.5: the final certificate gets a DocID unique in the world
		# (a UUID) and its creation date. A draft prints with the draft DocID only.
		self.doc_id = str(uuid.uuid4())
		self.finalized_on = now_datetime()

	def validate_mandatory_fields(self):
		"""Ensure all fields required for a valid Swiss salary certificate are present."""
		if not self.avs_number:
			frappe.throw(
				_("AVS Number is required for the salary certificate. Please update the employee record.")
			)
		if not self.date_of_birth:
			frappe.throw(
				_("Date of Birth is required for the salary certificate. Please update the employee record.")
			)
		if not self.posting_date:
			frappe.throw(_("Posting Date (certificate date) is required."))

	def set_period(self):
		"""Box E: the employment dates within the year (Wegleitung Rz 8)."""
		if not self.fiscal_year:
			return
		year_start, year_end = frappe.get_cached_value(
			"Fiscal Year", self.fiscal_year, ["year_start_date", "year_end_date"]
		)
		self.period_from, self.period_to = employment_period(
			getdate(year_start),
			getdate(year_end),
			getdate(self.date_of_joining) if self.date_of_joining else None,
			getdate(self.relieving_date) if self.relieving_date else None,
		)

	def round_positions(self):
		"""Whole francs in every box ("only whole franc amounts", Swissdec 6.0 9.1.2)."""
		for position, field in POSITION_FIELD_MAP.items():
			self.set(field, 0 if position in TEXT_ONLY_POSITIONS else to_francs(self.get(field)))

	def calculate_totals(self):
		"""Positions 8 (gross) and 11 (net), from the whole-franc boxes."""
		positions = {position: self.get(field) for position, field in POSITION_FIELD_MAP.items()}
		self.position_8_gross_income, self.position_11_net_salary = certificate_totals(positions)

	@frappe.whitelist()
	def populate_from_salary_slips(self):
		"""Populate certificate positions from submitted salary slips.

		Fetches all submitted Salary Slips for the employee/fiscal year and places every row
		by its component's certificate position, the configuration's mapping overriding it
		(see hrms/regional/switzerland/salary_certificate.py). Every position is recomputed:
		populating twice gives the same certificate.
		"""
		# //// Neoffice — two checks added. frappe.handler.run_doc_method asserts read on the
		# //// certificate and nothing else, and the aggregation below reads EVERY submitted Salary
		# //// Slip of the employee for the year through frappe.get_all, which bypasses the
		# //// permission layer: read on one certificate was enough to extract a whole payroll year.
		# //// write on the certificate too — this rewrites every Form 11 position on the document.
		self.check_permission("write")
		frappe.has_permission("Salary Slip", "read", throw=True)
		if not self.employee or not self.fiscal_year:
			frappe.throw(_("Employee and Fiscal Year are required."))

		slips = _slips_of_the_year(self.employee, self.company, self.fiscal_year)
		if not slips:
			frappe.msgprint(
				_("No submitted salary slips found for {0} in {1}.").format(
					self.employee_name, self.fiscal_year
				)
			)
			return

		# //// Neoffice — positions from the components themselves (salary_certificate.py): the
		# //// configuration's mapping only overrides. It used to be the only source, and its default
		# //// rows left bonuses, APG, maternity, family allowances and expenses off the certificate.
		employee = frappe.get_cached_doc("Employee", self.employee)
		config = get_swiss_social_insurance_config(self.company, employee.get("ch_fiscal_canton") or "")
		if self.language not in LANGUAGES:
			self.language = self._default_language(employee, config)
		result = certificate_positions(_get_slip_rows(slips), _mapping_overrides(config))

		for field in {*POSITION_FIELD_MAP.values(), *DESCRIPTION_FIELDS.values()}:
			if self.meta.has_field(field):
				self.set(field, "" if field in DESCRIPTION_FIELDS.values() else 0)
		for position, amount in result["totals"].items():
			field = POSITION_FIELD_MAP.get(position)
			if field and self.meta.has_field(field):
				self.set(field, amount)
		for position, labels in result["descriptions"].items():
			field = DESCRIPTION_FIELDS.get(position)
			if field and self.meta.has_field(field):
				self.set(field, ", ".join(_(label, lang=self.language) for label in labels)[:140])

		regulation = _expense_regulation(config)
		if regulation:
			# Wegleitung Rz 59 and 65: with an expense regulation approved by the canton, the
			# effective travel, meal and overnight expenses are not declared and 13.1.1 gets no
			# cross. 13.1.2 stays: expenses of an external workplace are declared in every case
			# (Rz 54), and a declared amount is never the error an omitted one is.
			self.position_13_1_1_travel = 0
			self.position_13_1_1_travel_check = 0

		year_end = getdate(frappe.get_cached_value("Fiscal Year", self.fiscal_year, "year_end_date"))
		source_tax = flt(self.position_12_withholding_tax) or cint(employee.get("ch_qst_subject"))
		self.remark_facts = frappe.as_json(
			{
				"slips": len(slips),
				"part_time_rate": flt(employee.get("ch_work_percentage")) or None,
				"expense_regulation": regulation,
				"short_time_work_in_box_1": result["short_time_work_in_box_1"],
				"replacement_in_box_1": result["replacement_in_box_1"],
				"withheld": result["withheld"],
				"family_allowances": result["family_allowances"],
				# The objection period ends on 31 March of the following year (standard remark).
				"tax_at_source_year": year_end.year + 1 if source_tax else None,
			}
		)
		self.round_positions()
		self.calculate_totals()
		self.position_15_remarks = "\n".join(self._remarks())

		frappe.msgprint(_("Certificate populated from {0} salary slips.").format(len(slips)))

	def _default_language(self, employee=None, config=None):
		"""The language of the tax administration of the employee's canton."""
		if not employee and self.employee:
			employee = frappe.get_cached_doc("Employee", self.employee)
		canton = (employee.get("ch_fiscal_canton") if employee else None) or (
			config.get("canton") if config else None
		)
		if not canton and self.company:
			config = get_swiss_social_insurance_config(self.company)
			canton = config.get("canton") if config else None
		return certificate_language(canton, frappe.db.get_default("lang"))

	def _remarks(self):
		"""Box 15 in the certificate's language (Wegleitung Rz 63-71, Swissdec standard remarks)."""
		facts = dict(frappe.parse_json(self.remark_facts) or {})
		language = self.language if self.language in LANGUAGES else "fr"
		for key in ("withheld", "replacement_in_box_1"):
			facts[key] = [
				{**entry, "label": _(entry.get("label") or "", lang=language)}
				for entry in facts.get(key) or []
			]
		facts["rectificate"] = self._rectificate()
		facts["number_of_certificates"] = self.number_of_certificates
		facts["benefit_days_by_insurer"] = self.benefit_days_by_insurer
		facts["additional_remarks"] = self.additional_remarks
		return build_remarks(facts, language)

	def _rectificate(self):
		"""The certificate this one replaces: its DocID and creation date (Swissdec 6.0, 9.1.6)."""
		if not self.amended_from:
			return None
		original = frappe.db.get_value(
			self.doctype,
			self.amended_from,
			["name", "doc_id", "finalized_on", "posting_date"],
			as_dict=True,
		)
		if not original:
			return None
		# A certificate validated before DocIDs existed carried its name as DocID in the barcode.
		return {
			"doc_id": original.doc_id or original.name,
			"date": str(getdate(original.finalized_on or original.posting_date)),
		}

	@frappe.whitelist()
	def get_delivery_options(self):
		"""What the Send dialog offers: the employee's addresses and whether the PDF is locked."""
		self.check_permission("email")
		settings = frappe.get_cached_doc("Payroll Settings")
		addresses = employee_email_addresses(self.employee)
		return {
			"addresses": addresses,
			"default": self.sent_to if self.sent_to in addresses else (addresses[0] if addresses else None),
			"password_policy": settings.password_policy if _encrypts_pdf(settings) else None,
			"sent_to": self.sent_to,
			"sent_to_employee_on": self.sent_to_employee_on,
		}

	@frappe.whitelist()
	def send_to_employee(self, recipient=None):
		"""Email the validated certificate to the employee, as a PDF in the certificate's language.

		The Wegleitung (Rz 74) addresses the certificate to the employee; it is due every year and
		at once when the employee leaves (Rz 7). The email goes out as a Communication, so the form
		keeps a trace of what was sent, to whom and when.
		"""
		if self.docstatus != 1:
			frappe.throw(_("Validate the certificate before sending it to the employee."))
		self.check_permission("email")

		addresses = employee_email_addresses(self.employee)
		recipient = (recipient or "").strip() or (addresses[0] if addresses else "")
		if not recipient:
			frappe.throw(
				_("{0} has no email address. Add one to the employee record.").format(self.employee_name)
			)
		if recipient not in addresses:
			frappe.throw(_("Choose one of the email addresses of the employee record."))

		from frappe.core.doctype.communication.email import make
		from frappe.translate import print_language

		language = self.language if self.language in LANGUAGES else "fr"
		settings = frappe.get_cached_doc("Payroll Settings")
		password = None
		if _encrypts_pdf(settings):
			from hrms.payroll.doctype.salary_slip.salary_slip import generate_password_for_pdf

			password = generate_password_for_pdf(settings.password_policy, self.employee)

		with print_language(language):
			pdf = frappe.get_print(
				self.doctype,
				self.name,
				print_format=self.meta.default_print_format or None,
				as_pdf=True,
				no_letterhead=1,
				password=password,
			)

		year = getdate(self.period_to or self.posting_date).year
		first_name = frappe.db.get_value("Employee", self.employee, "first_name") or self.employee_name
		paragraphs = [
			_("Hello {0},", lang=language).format(first_name),
			_(
				"Please find attached your salary certificate for {0}. Keep it with your tax return.",
				lang=language,
			).format(year),
		]
		if password:
			paragraphs.append(
				_("The PDF is protected by a password of the format {0}.", lang=language).format(
					settings.password_policy
				)
			)
		paragraphs.append(
			_("Kind regards", lang=language) + "<br>" + frappe.utils.escape_html(self._employer_name())
		)

		subject = _("Salary certificate {0}", lang=language).format(year)
		content = "<br><br>".join(paragraphs)
		sender = settings.get("sender_email") or None
		# The Communication is the trace on the certificate's timeline; the PDF goes with the email
		# itself, like the salary slips' (frappe.sendmail). Attached to the Communication instead,
		# it would be stored as a File first — which a File override of the Drive app (suite)
		# refuses for content passed in memory ("file does not exist", 2026-09-23 on osiris).
		communication = make(
			doctype=self.doctype,
			name=self.name,
			subject=subject,
			content=content,
			recipients=[recipient],
			sender=sender,
			send_email=False,
		)
		frappe.sendmail(
			recipients=[recipient],
			sender=sender,
			subject=subject,
			message=content,
			attachments=[{"fname": f"{self.name}.pdf", "fcontent": pdf}],
			reference_doctype=self.doctype,
			reference_name=self.name,
			communication=communication["name"],
		)
		self.db_set({"sent_to_employee_on": now_datetime(), "sent_to": recipient})
		return {"sent_to": recipient, "sent_to_employee_on": self.sent_to_employee_on}

	def _employer_name(self):
		config = get_swiss_social_insurance_config(self.company)
		return (config and config.get("lohnausweis_employer_name")) or self.company

	@frappe.whitelist()
	def get_barcode_data(self):
		"""Generate the Swissdec 2D barcode (annex 5) of this certificate.

		Returns a dict with base64-encoded PDF417 and CODE128C barcode images
		for embedding in the print format.
		"""
		from hrms.regional.switzerland.lohnausweis_barcode import generate_barcode_page_data

		# Collect employer info
		config = get_swiss_social_insurance_config(self.company)
		company = frappe.get_cached_doc("Company", self.company)
		employer_address = (config and config.get("lohnausweis_employer_address")) or ""
		# //// Neoffice — the UID is the Swiss field ch_uid_bfs (as in the ELM declaration), and the
		# //// employer's ZIP and city come from its certificate address: ERPNext's Company has no
		# //// pincode or city field, so both were always empty in the barcode.
		employer_zip, employer_city = _extract_zip_city(employer_address)
		employer_data = {
			"name": self._employer_name(),
			"address": employer_address,
			"uid_bfs": company.get("ch_uid_bfs") or company.get("tax_id") or "",
			"zip_code": employer_zip,
			"city": employer_city,
		}

		# Collect employee info (identity + address attributes for PersonID)
		emp = frappe.get_cached_doc("Employee", self.employee) if self.employee else None
		address = (emp.get("permanent_address") or emp.get("current_address")) if emp else ""
		emp_zip, emp_city = _extract_zip_city(address)
		employee_data = {
			"name": self.employee_name,
			"first_name": (emp.get("first_name") if emp else "") or "",
			"last_name": (emp.get("last_name") if emp else "") or "",
			"zip_code": emp_zip,
			"city": emp_city,
			"avs_number": self.avs_number or "",
			"date_of_birth": str(self.date_of_birth) if self.date_of_birth else "",
			"date_of_joining": str(self.date_of_joining) if self.date_of_joining else "",
			"relieving_date": str(self.relieving_date) if self.relieving_date else "",
		}

		# Collect all positions
		positions = {}
		for pos_key, field_name in POSITION_FIELD_MAP.items():
			positions[pos_key] = 0 if pos_key in TEXT_ONLY_POSITIONS else flt(self.get(field_name), 2)
		# Computed positions (not in POSITION_FIELD_MAP)
		positions["8"] = flt(self.position_8_gross_income, 2)
		positions["11"] = flt(self.position_11_net_salary, 2)
		positions["15"] = self.position_15_remarks or ""

		# Free-text descriptions feeding the TxAB SortSum elements
		descriptions = {position: self.get(field) or "" for position, field in DESCRIPTION_FIELDS.items()}

		certificate_data = {
			"employer": employer_data,
			"employee": employee_data,
			"fiscal_year": str(self.fiscal_year),
			"posting_date": str(self.posting_date) if self.posting_date else "",
			"positions": positions,
			"descriptions": descriptions,
			"free_transport": bool(self.get("free_transport")),
			"lunch_checks": bool(self.get("lunch_checks")),
			"certificate_id": self.barcode_doc_id(),
		}

		return generate_barcode_page_data(certificate_data)

	def barcode_doc_id(self):
		"""The DocID of the barcode: the UUID once validated, the draft marker before."""
		if self.docstatus == 0:
			return DRAFT_DOC_ID
		return self.doc_id or self.name

	def get_print_data(self):
		"""What the print format needs beyond the fields: box I and the draft marker.

		Box I (Wegleitung Rz 12): place and date, the employer's exact address, the person in
		charge of the certificate and their phone number. A draft prints as one (Swissdec 6.0,
		9.1.2): its DocID is the draft marker, and the page says so.
		"""
		config = get_swiss_social_insurance_config(self.company) or {}
		company = frappe.get_cached_doc("Company", self.company)
		address_lines = [
			line.strip()
			for line in (config.get("lohnausweis_employer_address") or "").splitlines()
			if line.strip()
		]
		_zip, city = _extract_zip_city("\n".join(address_lines))
		employee = frappe.get_cached_doc("Employee", self.employee)
		employee_address = employee.get("permanent_address") or employee.get("current_address") or ""
		remarks = self.position_15_remarks or ""
		return {
			"employer_name": self._employer_name(),
			"employer_address": ", ".join(address_lines),
			"place": city,
			"contact_person": company.get("ch_contact_person") or "",
			"contact_phone": company.get("ch_contact_phone") or "",
			"employee_address_lines": [
				line.strip() for line in employee_address.splitlines() if line.strip()
			],
			"remark_lines": [line for line in remarks.splitlines() if line.strip()],
			"remarks_font_pt": _remarks_font_size(remarks),
			"is_draft": self.docstatus == 0,
			"draft_marker": DRAFT_DOC_ID,
			"doc_id": self.barcode_doc_id(),
		}


def _remarks_font_size(remarks):
	"""Box 15 has two lines, ~300 characters at 8pt; the source tax remark alone is 430.

	The text shrinks rather than overflowing onto box I.
	"""
	for limit, size in ((250, 8), (450, 7), (750, 6)):
		if len(remarks) <= limit:
			return size
	return 5


@frappe.whitelist()
def get_barcode_data_for_print(name):
	"""Generate the Swissdec 2D barcode data of a Swiss Salary Certificate.

	Module-level whitelisted function callable from Jinja print formats.
	"""
	# //// Neoffice — permission check added. This is reachable as
	# //// /api/method/...get_barcode_data_for_print?name=CH-CERT-2026-HR-EMP-00001: unlike the
	# //// document method above (run_doc_method checks read), a module-level whitelist gets no
	# //// check at all, and frappe.get_doc never applies one. The payload it returns is the raw
	# //// TxAB record — AVS number, date of birth, address, every Form 11 position — and the
	# //// names are enumerable (format:CH-CERT-{fiscal_year}-{employee}). Printing is unaffected:
	# //// rendering a print format already requires read on the document.
	frappe.has_permission("Swiss Salary Certificate", "read", doc=name, throw=True)
	doc = frappe.get_doc("Swiss Salary Certificate", name)
	return doc.get_barcode_data()


def _extract_zip_city(address_text):
	"""Best-effort extraction of (zip, city) from a free-text Swiss address."""
	if not address_text:
		return "", ""
	match = re.search(r"\b(\d{4})\s+([A-Za-zÀ-ÿ'\. -]+)", address_text)
	if match:
		return match.group(1), match.group(2).strip().splitlines()[0].strip()
	return "", ""


# //// Neoffice — the description next to the positions that must name their benefit.
DESCRIPTION_FIELDS = {
	"2.3": "position_2_3_description",
	"3": "position_3_description",
	"4": "position_4_description",
	"7": "position_7_description",
	"13.1.2": "position_13_1_2_description",
	"13.2.3": "position_13_2_3_description",
	"14": "position_14_description",
}
# The mapping's old option values, finer on the certificate.
_LEGACY_POSITIONS = {"13.1": "13.1.1", "13.2": "13.2.3"}


def _slips_of_the_year(employee, company, fiscal_year):
	year_start, year_end = frappe.get_cached_value(
		"Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"]
	)
	return frappe.get_all(
		"Salary Slip",
		filters={
			"employee": employee,
			"company": company,
			"start_date": [">=", year_start],
			"end_date": ["<=", year_end],
			"docstatus": 1,
		},
		pluck="name",
	)


def _get_slip_rows(slip_names):
	"""Slip rows summed per component, with what the certificate needs to place them."""
	if not slip_names:
		return []
	rows = frappe.db.sql(
		"""SELECT sd.salary_component, sd.parentfield,
			COALESCE(sd.do_not_include_in_total, 0) AS do_not_include_in_total,
			SUM(sd.amount) AS amount,
			GROUP_CONCAT(DISTINCT DATE_FORMAT(ss.start_date, '%%Y-%%m')) AS months,
			sc.is_employer_contribution, sc.ch_wage_type_code, sc.ch_lohnausweis_position,
			sc.ch_bases_only, wt.lohnausweis_position AS wage_type_position
		FROM `tabSalary Detail` sd
		JOIN `tabSalary Slip` ss ON ss.name = sd.parent
		LEFT JOIN `tabSalary Component` sc ON sc.name = sd.salary_component
		LEFT JOIN `tabSwiss Wage Type` wt ON wt.name = CONCAT('CH-WT-', sc.ch_wage_type_code)
		WHERE sd.parent IN %s AND sd.parenttype = 'Salary Slip'
		GROUP BY sd.salary_component, sd.parentfield, COALESCE(sd.do_not_include_in_total, 0)""",
		(tuple(slip_names),),
		as_dict=True,
	)
	for row in rows:
		row["label"] = row.salary_component
	return rows


def _mapping_overrides(config):
	"""{component: position, or None when it is kept off the certificate} from the configuration."""
	if not config:
		return {}
	overrides = {}
	for row in frappe.get_all(
		"Swiss Lohnausweis Mapping",
		filters={"parent": config.name, "parenttype": "Swiss Social Insurance Config"},
		fields=["salary_component", "lohnausweis_position", "include_in_certificate"],
	):
		position = _LEGACY_POSITIONS.get(row.lohnausweis_position, row.lohnausweis_position)
		overrides[row.salary_component] = position if row.include_in_certificate else None
	return overrides


def _expense_regulation(config):
	"""{canton, date} of the expense regulation the canton approved, when the config names one."""
	if not config:
		return None
	canton = config.get("lohnausweis_expense_regulation_canton")
	approved_on = config.get("lohnausweis_expense_regulation_date")
	if canton and approved_on:
		return {"canton": canton, "date": str(getdate(approved_on))}
	return None


def _encrypts_pdf(settings):
	return bool(cint(settings.get("encrypt_salary_slips_in_emails")) and settings.get("password_policy"))


def employee_email_addresses(employee):
	"""The employee's addresses, the preferred one first."""
	row = (
		frappe.db.get_value(
			"Employee",
			employee,
			["prefered_email", "personal_email", "company_email", "user_id"],
			as_dict=True,
		)
		or {}
	)
	addresses = []
	for value in (
		row.get("prefered_email"),
		row.get("personal_email"),
		row.get("company_email"),
		row.get("user_id"),
	):
		value = (value or "").strip()
		if value and "@" in value and value not in addresses:
			addresses.append(value)
	return addresses


# //// Neoffice — employees read their own certificates (the mobile app, the portal): once
# //// validated, never a draft, never a colleague's. The Employee role's DocPerm grants read and
# //// print; these hooks narrow it to the employee's own records, whatever User Permissions the
# //// site has (a user with the Employee role and no User Permission would otherwise read every
# //// certificate of the company).
def _is_payroll_staff(user):
	return user == "Administrator" or bool(set(PAYROLL_STAFF_ROLES) & set(frappe.get_roles(user)))


def _employees_of(user):
	return frappe.get_all("Employee", filters={"user_id": user}, pluck="name")


def has_permission(doc, ptype=None, user=None, debug=False):
	user = user or frappe.session.user
	if _is_payroll_staff(user):
		return None
	if doc.docstatus != 1:
		return False
	return doc.employee in _employees_of(user)


def get_permission_query_conditions(user=None, doctype=None):
	user = user or frappe.session.user
	if _is_payroll_staff(user):
		return ""
	employees = _employees_of(user)
	if not employees:
		return "1=0"
	names = ", ".join(frappe.db.escape(name) for name in employees)
	return (
		"(`tabSwiss Salary Certificate`.docstatus = 1 "
		f"and `tabSwiss Salary Certificate`.employee in ({names}))"
	)
