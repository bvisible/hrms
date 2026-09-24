# //// Neoffice — added file (no upstream equivalent): the last step of the monthly payroll cycle,
# //// the payslips reaching the employees — by e-mail, by post (WebStamp) or handed out.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Hand out the payslips of a period.

Each employee has a channel (Employee.ch_payslip_delivery): Email, By Post (franked with a WebStamp
and mailed in a window envelope) or By Hand (printed and handed out) — "Post" alone is Frappe's
verb, "Poster". Without one, the channel is Email when the employee has an address, else By Hand.
The channel used is remembered for the next month.

A payslip counts as delivered once e-mailed (its Email Queue) or printed from here (ch_printed_on,
set by mark_printed — by hand, or by post with its stamp). A stamp alone is not delivery: the
payslip still has to be printed and posted.

Submitting a slip in the cycle sends nothing (monthly_cycle.submit_cycle): the e-mail leaves here,
when payroll staff decide, in the payslip's own print format and with a message in the reader's
language rather than upstream's fixed English subject.
"""

import json

import frappe
from frappe import _
from frappe.utils import formatdate, getdate, now_datetime

from hrms.regional.switzerland.permissions import check_payroll_staff
from hrms.regional.switzerland.utils import get_webstamp_image

CHANNELS = ("Email", "By Post", "By Hand")
PRINT_FORMAT = "Salary Slip Swiss"
# Email Queue states that mean the payslip went, or is on its way.
SENT_STATES = ("Not Sent", "Sending", "Sent", "Partially Sent")


def _period_bounds(year, month):
	from hrms.regional.switzerland.monthly_cycle import _period_bounds as bounds

	return bounds(year, month)


def period_label(end_date):
	"""« Mai 2027 »: the month in the reader's language, capitalised."""
	label = formatdate(getdate(end_date), "MMMM yyyy")
	return label[:1].upper() + label[1:]


def default_channel(delivery, email):
	return delivery if delivery in CHANNELS else ("Email" if email else "By Hand")


def _slips(company, year, month, names=None):
	start, _end = _period_bounds(year, month)
	filters = {"company": company, "start_date": start, "docstatus": 1}
	if names is not None:
		filters["name"] = ["in", list(names) or [""]]
	fields = ["name", "employee", "employee_name", "net_pay", "end_date", "company"]
	if frappe.db.has_column("Salary Slip", "ch_printed_on"):
		fields.append("ch_printed_on")
	return frappe.get_all("Salary Slip", filters=filters, fields=fields, order_by="employee_name")


def _names(slips):
	if isinstance(slips, str):
		slips = json.loads(slips)
	return [str(name) for name in slips or []]


@frappe.whitelist()
def get_distribution(company, year, month):
	"""The submitted payslips of the period, each with its channel and what was already done."""
	check_payroll_staff(company)
	slips = _slips(company, year, month)
	names = [s.name for s in slips]
	has_channel = frappe.db.has_column("Employee", "ch_payslip_delivery")
	employees = {
		e.name: e
		for e in frappe.get_all(
			"Employee",
			filters={"name": ["in", [s.employee for s in slips] or [""]]},
			fields=["name", "prefered_email", "permanent_address", "current_address"]
			+ (["ch_payslip_delivery"] if has_channel else []),
		)
	}
	emailed = set(
		frappe.get_all(
			"Email Queue",
			filters={
				"reference_doctype": "Salary Slip",
				"reference_name": ["in", names or [""]],
				"status": ["in", SENT_STATES],
			},
			pluck="reference_name",
		)
	)
	rows = []
	for slip in slips:
		employee = employees.get(slip.employee) or frappe._dict()
		rows.append(
			{
				"slip": slip.name,
				"employee": slip.employee,
				"employee_name": slip.employee_name,
				"net_pay": slip.net_pay,
				"email": employee.get("prefered_email") or "",
				"has_address": bool(
					(employee.get("current_address") or employee.get("permanent_address") or "").strip()
				),
				"channel": default_channel(
					employee.get("ch_payslip_delivery"), employee.get("prefered_email")
				),
				"emailed": slip.name in emailed,
				"stamp_url": get_webstamp_image(frappe._dict(doctype="Salary Slip", name=slip.name)),
				"printed_on": slip.get("ch_printed_on"),
			}
		)
	return {
		"rows": rows,
		"print_format": PRINT_FORMAT if frappe.db.exists("Print Format", PRINT_FORMAT) else None,
		"webstamp": "swisspost_barcode" in frappe.get_installed_apps(),
	}


@frappe.whitelist(methods=["POST"])
def set_channel(company, employee, channel):
	"""Remember how an employee receives the payslip."""
	check_payroll_staff(company)
	if channel not in CHANNELS:
		frappe.throw(_("Unknown payslip delivery: {0}").format(channel))
	if frappe.db.get_value("Employee", employee, "company") != company:
		frappe.throw(_("Employee {0} does not belong to the company {1}.").format(employee, company))
	frappe.db.set_value("Employee", employee, "ch_payslip_delivery", channel)
	return channel


@frappe.whitelist(methods=["POST"])
def send_payslips(company, year, month, slips):
	"""E-mail the given payslips of the period to their employees, the Swiss print attached.

	Rendering a PDF takes a second or two, so each e-mail is prepared in the background, as upstream
	does. Returns the slips sent and those whose employee has no e-mail address.
	"""
	check_payroll_staff(company)
	# The e-mails are prepared in the background: without an outgoing account they would fail there,
	# unseen, while this answered "on their way". Frappe's own message says which account to set up.
	from frappe.email.doctype.email_account.email_account import EmailAccount

	EmailAccount.find_outgoing(match_by_doctype="Salary Slip", _raise_error=True)
	sent, without_email = [], []
	for slip in _slips(company, year, month, _names(slips)):
		receiver = frappe.db.get_value("Employee", slip.employee, "prefered_email")
		if not receiver:
			without_email.append(slip.employee_name)
			continue
		args = {"slip": slip.name, "receiver": receiver, "lang": frappe.local.lang}
		if frappe.flags.in_test:
			email_payslip(**args)
		else:
			frappe.enqueue(
				"hrms.regional.switzerland.distribution.email_payslip", queue="short", timeout=300, **args
			)
		_remember(slip.employee, "Email")
		sent.append(slip.name)
	return {"sent": sent, "without_email": without_email}


def email_payslip(slip, receiver, lang=None):
	"""One payslip by e-mail: the payroll settings' template when there is one, else our message."""
	if lang:
		frappe.local.lang = lang
	doc = frappe.get_doc("Salary Slip", slip)
	settings = frappe.get_single("Payroll Settings")
	period = period_label(doc.end_date)
	subject = _("Salary slip {0} — {1}").format(period, doc.company)
	greeting = _("Hello {0},").format(frappe.utils.escape_html(doc.employee_name))
	body = _("Please find attached your salary slip for {0}.").format(period)
	message = f"<p>{greeting}</p><p>{body}</p><p>{frappe.utils.escape_html(doc.company)}</p>"
	if settings.email_template:
		template = frappe.get_doc("Email Template", settings.email_template)
		context = doc.as_dict()
		subject = frappe.render_template(template.subject, context)
		message = frappe.render_template(template.response, context)
	password = None
	if settings.encrypt_salary_slips_in_emails:
		from hrms.payroll.doctype.salary_slip.salary_slip import generate_password_for_pdf

		password = generate_password_for_pdf(settings.password_policy, doc.employee)
		if not settings.email_template:
			note = _(
				"Note: Your salary slip is password protected, the password to unlock the PDF is of the format {0}."
			).format(settings.password_policy)
			message += f"<p>{note}</p>"
	print_format = PRINT_FORMAT if frappe.db.exists("Print Format", PRINT_FORMAT) else None
	# frappe.attach_print drops the spaces of a file name ("SalaryslipApril2027…"): hyphens instead.
	file_name = "-".join(f"{_('Salary slip')} {period} {doc.employee_name}".split())
	frappe.sendmail(
		sender=settings.sender_email,
		recipients=[receiver],
		subject=subject,
		message=message,
		attachments=[
			frappe.attach_print(
				"Salary Slip",
				doc.name,
				file_name=file_name,
				print_format=print_format,
				password=password,
			)
		],
		reference_doctype="Salary Slip",
		reference_name=doc.name,
	)


@frappe.whitelist()
def get_stamp_plan(company, year, month, slips):
	"""What the franking dialog offers: the given payslips grouped by Swiss Post zone (at home,
	Europe, the other countries), each group with its letter products and its recipients.

	A product serves one zone: the page orders each group with the product picked for it.
	"""
	check_payroll_staff(company)
	from hrms.regional.switzerland import webstamp

	config = webstamp._require_app()
	catalogue = webstamp._catalogue(config)
	groups = {}
	for slip in _slips(company, year, month, _names(slips)):
		recipient = webstamp.payslip_recipient(slip)
		zone = webstamp.recipient_zone(recipient["country"], config)
		group = groups.setdefault(
			zone,
			{
				"zone": zone,
				"slips": [],
				"recipients": [],
				"products": webstamp.letter_products(catalogue, zone),
			},
		)
		group["slips"].append(slip.name)
		town = " ".join(part for part in (recipient["zip"], recipient["city"]) if part)
		group["recipients"].append(
			{
				"employee_name": slip.employee_name,
				"address": ", ".join(part for part in (recipient["street"], town) if part),
				"country": _(recipient["country_name"]) if zone != webstamp.DOMESTIC_ZONE else "",
			}
		)
	order = {webstamp.DOMESTIC_ZONE: 0}
	return {
		"environment": webstamp._environment(config),
		"groups": sorted(groups.values(), key=lambda g: order.get(g["zone"], g["zone"])),
	}


@frappe.whitelist(methods=["POST"])
def stamp_payslips(company, year, month, slips, product_number, product_name=None, product_price=None):
	"""Frank the given payslips with a WebStamp each (webstamp.stamp_salary_slip), for the post.

	Returns the slips franked and, for the others, why not (an incomplete address, an error of the
	WebStamp service).
	"""
	check_payroll_staff(company)
	from hrms.regional.switzerland.webstamp import stamp_salary_slip

	stamped, failed = [], []
	for slip in _slips(company, year, month, _names(slips)):
		try:
			result = stamp_salary_slip(slip.name, product_number, product_name, product_price, preview=0)
		except frappe.ValidationError as e:
			failed.append({"slip": slip.name, "employee_name": slip.employee_name, "error": str(e)})
			continue
		if result.get("success"):
			stamped.append(slip.name)
			_remember(slip.employee, "By Post")
		else:
			failed.append(
				{"slip": slip.name, "employee_name": slip.employee_name, "error": result.get("message") or ""}
			)
	return {"stamped": stamped, "failed": failed}


@frappe.whitelist(methods=["POST"])
def mark_printed(company, year, month, slips):
	"""The given payslips were printed: note when on each slip (ch_printed_on).

	A payslip printed without a stamp is handed out, which is remembered as that employee's channel;
	one with a stamp goes by post and its channel stays. Returns the slips marked.
	"""
	check_payroll_staff(company)
	marked = []
	has_column = frappe.db.has_column("Salary Slip", "ch_printed_on")
	for slip in _slips(company, year, month, _names(slips)):
		if has_column:
			frappe.db.set_value(
				"Salary Slip", slip.name, "ch_printed_on", now_datetime(), update_modified=False
			)
		if not get_webstamp_image(frappe._dict(doctype="Salary Slip", name=slip.name)):
			_remember(slip.employee, "By Hand")
		marked.append(slip.name)
	return marked


def _remember(employee, channel):
	if frappe.db.has_column("Employee", "ch_payslip_delivery"):
		frappe.db.set_value("Employee", employee, "ch_payslip_delivery", channel, update_modified=False)
