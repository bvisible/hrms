# //// Neoffice — added file (no upstream equivalent): the whitelisted endpoints of the Swiss
# //// payroll module answer the API, not only the desk page. Every one of them reads or writes
# //// payroll through frappe.get_all / frappe.db.sql / ignore_permissions, all of which bypass
# //// the permission layer — so the check has to live in the endpoint, and it has to be tested
# //// from a session that is NOT Administrator (who passes everything by construction).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.regional.switzerland import (
	accounting,
	api,
	distribution,
	employee_wizard,
	insurer_statements,
	monthly_cycle,
	payment_file,
	webstamp,
	year_end,
)

WEBSITE_USER = "swiss-payroll-portal-test@yopmail.com"


def _ensure_website_user():
	"""A portal customer: user_type Website User, not one desk role."""
	if not frappe.db.exists("User", WEBSITE_USER):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": WEBSITE_USER,
				"first_name": "Swiss Portal",
				"send_welcome_email": 0,
				"user_type": "Website User",
			}
		)
		user.flags.ignore_permissions = True
		user.insert(ignore_permissions=True)
	else:
		user = frappe.get_doc("User", WEBSITE_USER)
		user.set("roles", [])
		user.user_type = "Website User"
		user.save(ignore_permissions=True)
	return user.name


class SwissEndpointPermissionCase(FrappeTestCase):
	"""Shared fixture: a Website User session, restored to Administrator after each test."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.website_user = _ensure_website_user()

	def tearDown(self):
		# run-tests keeps one process for the whole file: a test that left the session on the
		# portal user would break every test after it.
		frappe.set_user("Administrator")
		super().tearDown()

	def assertRefused(self, fn, *args, **kwargs):
		"""The callable must raise PermissionError for the current (non-admin) session."""
		with self.assertRaises(frappe.PermissionError):
			fn(*args, **kwargs)


class TestPayrollReadEndpointsRefuseWebsiteUser(SwissEndpointPermissionCase):
	"""A portal customer must not be able to read the company's payroll through the API."""

	def setUp(self):
		self.company = frappe.db.get_value(
			"Company", {"country": "Switzerland"}, "name"
		) or frappe.db.get_value("Company", {}, "name")
		self.fiscal_year = frappe.db.get_value("Fiscal Year", {}, "name")

	def test_monthly_cycle_preflight_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(monthly_cycle.preflight, self.company, 2026, 1)

	def test_monthly_cycle_summary_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(monthly_cycle.summary, self.company, 2026, 1)

	def test_monthly_cycle_generate_refuses(self):
		# frappe.db.commit is stubbed on purpose: generate() commits per slip, so a regression
		# here would write to the site through a test that is supposed to roll back.
		frappe.set_user(self.website_user)
		with patch.object(frappe.db, "commit"):
			self.assertRefused(monthly_cycle.generate, self.company, 2026, 1)

	def test_monthly_cycle_submit_refuses(self):
		frappe.set_user(self.website_user)
		with patch.object(frappe.db, "commit"):
			self.assertRefused(monthly_cycle.submit_cycle, self.company, 2026, 1)

	def test_year_end_reconcile_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(year_end.reconcile, self.company, self.fiscal_year)

	def test_year_end_qst_summary_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(year_end.qst_summary, self.company, self.fiscal_year)

	def test_year_end_csv_export_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(year_end.export_year_end_csv, self.company, self.fiscal_year, "qst")

	def test_year_end_generate_certificates_refuses(self):
		frappe.set_user(self.website_user)
		with patch.object(frappe.db, "commit"):
			self.assertRefused(year_end.generate_certificates, self.company, self.fiscal_year)

	def test_administrator_still_passes(self):
		"""The gate must not break the legitimate caller."""
		result = monthly_cycle.summary(self.company, 2026, 1)
		self.assertIn("slips", result)


class TestQstTariffImportRefusesWebsiteUser(SwissEndpointPermissionCase):
	"""Wiping and re-importing the 26 cantonal ESTV tariffs is not a portal-user action."""

	def test_fetch_all_cantons_refuses(self):
		from hrms.payroll.doctype.swiss_qst_tariff.swiss_qst_tariff import fetch_all_cantons

		# frappe.enqueue is stubbed on purpose: should the gate ever regress, this test must
		# not be the thing that downloads the national ESTV archive and rewrites the millions
		# of bracket rows the payroll withholds from.
		frappe.set_user(self.website_user)
		with patch("frappe.enqueue") as enqueue:
			# //// Neoffice — was the French "Salaires" (b62d7bdeb "fix(swiss-payroll): the tariff
			# //// type, the field labels and the payslip wording leave French behind")
			self.assertRefused(fetch_all_cantons, 2026, "Salary")
		enqueue.assert_not_called()


class TestSalaryComponentCreationRefusesWebsiteUser(SwissEndpointPermissionCase):
	"""create_salary_component_from_wage_type inserts with ignore_permissions."""

	def test_create_salary_component_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(api.create_salary_component_from_wage_type, "1000")


class TestSalaryCertificateBarcodeRefusesWebsiteUser(SwissEndpointPermissionCase):
	"""The barcode payload is the whole TxAB record: AVS number, birth date, every position."""

	def test_barcode_for_print_refuses(self):
		from hrms.payroll.doctype.swiss_salary_certificate.swiss_salary_certificate import (
			get_barcode_data_for_print,
		)

		certificate = frappe.db.get_value("Swiss Salary Certificate", {}, "name")
		if not certificate:
			self.skipTest("no Swiss Salary Certificate on this site")

		frappe.set_user(self.website_user)
		self.assertRefused(get_barcode_data_for_print, certificate)


class TestChatSessionOwnership(SwissEndpointPermissionCase):
	"""A session belongs to the user who opened it: reading it, writing to it, applying it."""

	def setUp(self):
		self.session = frappe.get_doc(
			{
				"doctype": "Swiss Payroll Chat Session",
				"user": "Administrator",
				"status": "Active",
				"current_step": "company_setup",
			}
		).insert(ignore_permissions=True)

	def test_send_message_refuses_a_foreign_session(self):
		frappe.set_user(self.website_user)
		self.assertRefused(api.chat_send_message, self.session.name, "hello")

	def test_apply_step_refuses_a_foreign_session(self):
		frappe.set_user(self.website_user)
		self.assertRefused(api.chat_apply_step, self.session.name)

	def test_get_session_refuses_a_foreign_session(self):
		frappe.set_user(self.website_user)
		self.assertRefused(api.chat_get_session, self.session.name)

	def test_owner_still_reads_its_own_session(self):
		"""The gate must not lock the owner out of their own session."""
		data = api.chat_get_session(self.session.name)
		self.assertEqual(data["session_id"], self.session.name)


# //// Neoffice — added: the two classes below cover the whitelisted DOCUMENT methods, which the
# //// classes above do not reach. They take a different route into the app (run_doc_method
# //// instead of a module-level whitelist) and that route asserts read only, so they need their
# //// own proof that a portal session is refused and Administrator is not.
class TestWhitelistedDocumentMethodsRefuseWebsiteUser(SwissEndpointPermissionCase):
	"""run_doc_method asserts READ and nothing else before calling a whitelisted document
	method (frappe/handler.py: `if not doc or not doc.has_permission("read")`). Every method
	below writes — transmit() files the declaration with the authorities — so read was the
	only thing standing between a portal account and a filed salary declaration.

	Each method is called on an in-memory document: the check is the first statement of the
	body, so a refusal here is the gate and nothing else. The companion test in
	TestWhitelistedDocumentMethodsStillPassAdministrator proves the gate is what refuses,
	by showing Administrator reaching the body's own validation error instead.
	"""

	def setUp(self):
		self.declaration = frappe.get_doc({"doctype": "Swissdec Declaration"})
		self.ema = frappe.get_doc({"doctype": "Swissdec EMA Notification"})
		self.certificate = frappe.get_doc({"doctype": "Swiss Salary Certificate"})

	def test_declaration_populate_employees_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(self.declaration.populate_employees)

	def test_declaration_run_validation_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(self.declaration.run_validation)

	def test_declaration_export_xml_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(self.declaration.export_xml)

	def test_declaration_transmit_refuses(self):
		"""The one that files the declaration with the authorities."""
		frappe.set_user(self.website_user)
		with patch("hrms.regional.switzerland.swissdec_transmitter.transmit_declaration") as transmit:
			self.assertRefused(self.declaration.transmit)
		transmit.assert_not_called()

	def test_declaration_check_status_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(self.declaration.check_status)

	def test_declaration_retransmit_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(self.declaration.retransmit)

	def test_declaration_import_bvg_response_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(self.declaration.import_bvg_response, [])

	def test_ema_populate_from_employee_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(self.ema.populate_from_employee)

	def test_ema_export_xml_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(self.ema.export_xml)

	def test_ema_transmit_refuses(self):
		frappe.set_user(self.website_user)
		with patch("hrms.regional.switzerland.swissdec_transmitter.transmit_declaration") as transmit:
			self.assertRefused(self.ema.transmit)
		transmit.assert_not_called()

	def test_ema_check_status_refuses(self):
		frappe.set_user(self.website_user)
		self.assertRefused(self.ema.check_status)

	def test_certificate_populate_from_salary_slips_refuses(self):
		"""It aggregates every submitted Salary Slip of the year through frappe.get_all."""
		frappe.set_user(self.website_user)
		self.assertRefused(self.certificate.populate_from_salary_slips)

	def test_transmitter_settings_test_connection_refuses(self):
		"""It saves the Single and sends the stored API key to the configured URL."""
		settings = frappe.get_doc("Swissdec Transmitter Settings")
		frappe.set_user(self.website_user)
		# call_gateway is stubbed on purpose: should the gate regress, this test must not be
		# the thing that opens a connection carrying the instance's gateway API key.
		with patch("hrms.regional.switzerland.swissdec_transmitter.call_gateway") as call_gateway:
			self.assertRefused(settings.test_connection)
		call_gateway.assert_not_called()


class TestWhitelistedDocumentMethodsStillPassAdministrator(SwissEndpointPermissionCase):
	"""The gates must refuse the portal user, not everybody.

	Administrator short-circuits frappe.has_permission, so each method must get PAST the new
	check and fail on its own precondition instead — which is what tells a real gate apart
	from a method that would refuse anyone.
	"""

	def test_declaration_transmit_reaches_its_own_status_check(self):
		declaration = frappe.get_doc({"doctype": "Swissdec Declaration", "status": "Draft"})
		with self.assertRaises(frappe.ValidationError) as caught:
			declaration.transmit()
		self.assertNotIsInstance(caught.exception, frappe.PermissionError)
		self.assertIn("Exported", str(caught.exception))

	def test_declaration_populate_employees_reaches_its_own_field_check(self):
		declaration = frappe.get_doc({"doctype": "Swissdec Declaration"})
		with self.assertRaises(frappe.ValidationError) as caught:
			declaration.populate_employees()
		self.assertNotIsInstance(caught.exception, frappe.PermissionError)

	def test_ema_transmit_reaches_its_own_status_check(self):
		ema = frappe.get_doc({"doctype": "Swissdec EMA Notification", "status": "Draft"})
		with self.assertRaises(frappe.ValidationError) as caught:
			ema.transmit()
		self.assertNotIsInstance(caught.exception, frappe.PermissionError)
		self.assertIn("Exported", str(caught.exception))

	def test_certificate_populate_reaches_its_own_field_check(self):
		certificate = frappe.get_doc({"doctype": "Swiss Salary Certificate"})
		with self.assertRaises(frappe.ValidationError) as caught:
			certificate.populate_from_salary_slips()
		self.assertNotIsInstance(caught.exception, frappe.PermissionError)


# //// Neoffice — added (2026-09-23): an EMPLOYEE, not a portal customer. The Employee role reads
# //// Salary Slip (their own slips, through a User Permission), so the gates that only asked for
# //// read on Salary Slip let an ordinary employee read the payroll of the whole company.
EMPLOYEE_USER = "swiss-payroll-employee-test@yopmail.com"
HR_USER = "swiss-payroll-hr-test@yopmail.com"


def _ensure_desk_user(email, roles):
	"""A desk user holding exactly ``roles``, and none of the User Permissions of a past run."""
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		)
		user.flags.ignore_permissions = True
		user.insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	user.set("roles", [{"role": role} for role in roles])
	user.save(ignore_permissions=True)
	frappe.db.delete("User Permission", {"user": email})
	return user.name


def _restrict(user, allow, value):
	frappe.get_doc(
		{
			"doctype": "User Permission",
			"user": user,
			"allow": allow,
			"for_value": value,
			"apply_to_all_doctypes": 1,
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(user=user)


class TestPayrollOfTheCompanyRefusesAnEmployee(SwissEndpointPermissionCase):
	"""An employee reads their own slips, never the payroll of the company."""

	def setUp(self):
		self.company = frappe.db.get_value(
			"Company", {"country": "Switzerland"}, "name"
		) or frappe.db.get_value("Company", {}, "name")
		self.fiscal_year = frappe.db.get_value("Fiscal Year", {}, "name")
		# As the employees of a real site are: desk users linked to their Employee record, holding
		# the Employee role (ERPNext drops it from a user no employee is linked to) and the User
		# Permission ERPNext gives them on their own record.
		self.employee_user = _ensure_desk_user(EMPLOYEE_USER, ["Desk User"])
		self.employee = self._employee_of(self.employee_user)
		_ensure_desk_user(EMPLOYEE_USER, ["Employee", "Desk User"])
		_restrict(self.employee_user, "Employee", self.employee)
		self.hr_user = _ensure_desk_user(HR_USER, ["HR User", "Desk User"])

	def _employee_of(self, user):
		name = frappe.db.get_value("Employee", {"user_id": user}, "name")
		if name:
			return name
		return (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": "Swiss",
					"last_name": "EmployeeTest",
					"company": self.company,
					"gender": frappe.db.get_value("Gender", {}, "name"),
					"date_of_birth": "1990-01-01",
					"date_of_joining": "2020-01-01",
					"status": "Active",
					"user_id": user,
					"create_user_permission": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def endpoints(self):
		return (
			(year_end.reconcile, (self.company, self.fiscal_year)),
			(year_end.qst_summary, (self.company, self.fiscal_year)),
			(year_end.export_year_end_csv, (self.company, self.fiscal_year, "avs")),
			(monthly_cycle.preflight, (self.company, 2026, 1)),
			(monthly_cycle.summary, (self.company, 2026, 1)),
			# //// Neoffice — 2026-09-24: IBANs and nets of the whole company, role-gated only before.
			(payment_file.get_salary_payments, (self.company, 2026, 1)),
			(payment_file.download_pain001, (self.company, 2026, 1)),
			# //// Neoffice — 2026-09-24: the payslips of the company, e-mailed, franked or printed.
			(distribution.get_distribution, (self.company, 2026, 1)),
			(distribution.send_payslips, (self.company, 2026, 1, [])),
			(distribution.stamp_payslips, (self.company, 2026, 1, [], 1)),
			(distribution.get_stamp_plan, (self.company, 2026, 1, [])),
			(distribution.mark_printed, (self.company, 2026, 1, [])),
			(distribution.set_channel, (self.company, self.employee, "Email")),
		)

	def test_the_company_payroll_refuses_an_employee(self):
		frappe.set_user(self.employee_user)
		# The trap: read on Salary Slip passes, for their own slips.
		self.assertTrue(frappe.has_permission("Salary Slip", "read"))
		for fn, args in self.endpoints():
			with self.subTest(fn.__name__):
				self.assertRefused(fn, *args)

	# //// Neoffice — 2026-09-24: franking a payslip reads the employee's postal address and bills
	# //// the company's WebStamp account: payroll staff of the company only.
	def test_franking_a_payslip_refuses_an_employee(self):
		slip = frappe.db.get_value("Salary Slip", {"company": self.company}, "name")
		if not slip:
			self.skipTest("no salary slip of the company on this site")
		frappe.set_user(self.employee_user)
		self.assertRefused(webstamp.get_stamp_options, slip)
		self.assertRefused(webstamp.stamp_salary_slip, slip, 1)

	def test_the_payroll_assistant_refuses_an_employee(self):
		frappe.set_user(self.employee_user)
		self.assertRefused(api.chat_start_session, self.company)

	def test_payroll_staff_still_read_it(self):
		frappe.set_user(self.hr_user)
		self.assertIn("cantons", year_end.qst_summary(self.company, self.fiscal_year))
		self.assertIn("employees", year_end.reconcile(self.company, self.fiscal_year))

	def test_staff_limited_to_some_employees_do_not(self):
		_restrict(self.hr_user, "Employee", self.employee)
		frappe.set_user(self.hr_user)
		self.assertRefused(year_end.qst_summary, self.company, self.fiscal_year)

	def test_staff_limited_to_another_company_do_not(self):
		other = frappe.db.get_value("Company", {"name": ["!=", self.company]}, "name")
		if not other:
			self.skipTest("a single company on this site")
		_restrict(self.hr_user, "Company", other)
		frappe.set_user(self.hr_user)
		self.assertRefused(year_end.qst_summary, self.company, self.fiscal_year)


# //// Neoffice — added (2026-09-24): the endpoints the audit for the HR assistant found checking a
# //// role and not the company. Staff limited to one company read the IBANs and nets of another,
# //// booked its salaries, set its accounts, hired into it, or had the assistant write into it.
HR_MANAGER_USER = "swiss-payroll-hr-manager-test@yopmail.com"


class TestCompanyScopedEndpointsRefuseAnotherCompany(SwissEndpointPermissionCase):
	"""Payroll staff limited to one company act on that company only."""

	def setUp(self):
		self.company = frappe.db.get_value(
			"Company", {"country": "Switzerland"}, "name"
		) or frappe.db.get_value("Company", {}, "name")
		self.other = frappe.db.get_value("Company", {"name": ["!=", self.company]}, "name")
		if not self.other:
			self.skipTest("a single company on this site")
		self.manager = _ensure_desk_user(HR_MANAGER_USER, ["HR Manager", "Desk User"])
		_restrict(self.manager, "Company", self.other)

	def test_the_other_company_is_refused(self):
		frappe.set_user(self.manager)
		for fn, args in (
			(payment_file.get_salary_payments, (self.company, 2026, 1)),
			(payment_file.download_pain001, (self.company, 2026, 1)),
			(accounting.configure_payroll_accounts, (self.company,)),
			(accounting.post_payroll_accrual, (self.company, 2026, 1)),
			(insurer_statements.statement_defaults, (self.company,)),
			(employee_wizard.create_employee, ({"company": self.company, "first_name": "Refused"},)),
		):
			with self.subTest(fn.__name__):
				self.assertRefused(fn, *args)

	def test_the_assistant_refuses_a_company_named_in_the_conversation(self):
		session = frappe.get_doc(
			{
				"doctype": "Swiss Payroll Chat Session",
				"user": self.manager,
				"status": "Active",
				"current_step": "company_setup",
			}
		).insert(ignore_permissions=True)
		session.set_collected_data({"company": self.company, "uid_bfs": "CHE-123.456.789"})
		session.save(ignore_permissions=True)
		frappe.set_user(self.manager)
		self.assertRefused(api.chat_apply_step, session.name)

	def test_their_own_company_still_passes(self):
		frappe.set_user(self.manager)
		self.assertIn("insurer", insurer_statements.statement_defaults(self.other))
		self.assertIsInstance(payment_file.get_salary_payments(self.other, 2026, 1), dict)
