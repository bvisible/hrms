import frappe
from frappe.utils import add_months, get_first_day, get_last_day, getdate, now_datetime

from erpnext.setup.doctype.department.department import get_abbreviated_name
from erpnext.setup.doctype.designation.test_designation import create_designation
from erpnext.setup.utils import enable_all_roles_and_domains


def before_tests():
	frappe.clear_cache()
	# complete setup if missing
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	year = now_datetime().year
	if not frappe.get_list("Company"):
		setup_complete(
			{
				"currency": "INR",
				"full_name": "Test User",
				"company_name": "_Test Company",
				"timezone": "Asia/Kolkata",
				"company_abbr": "_TC",
				"industry": "Manufacturing",
				"country": "India",
				"fy_start_date": f"{year}-01-01",
				"fy_end_date": f"{year}-12-31",
				"language": "english",
				"company_tagline": "Testing",
				"email": "test@erpnext.com",
				"password": "test",
				"chart_of_accounts": "Standard",
			}
		)

		#//// Neoffice — the wizard swallows its own exceptions (setup_complete logs them and
		#//// returns a failure dict), and the test run then dies far away on a missing test
		#//// company. Surface the real error instead (CI diagnostic, 2026-09-04).
		if not frappe.get_list("Company"):
			for row in frappe.get_all("Error Log", fields=["method", "error"], order_by="creation desc", limit=3):
				print("SETUP WIZARD ERROR LOG:", row.method, "\n", (row.error or "")[-1500:])
			raise RuntimeError("setup_complete left no Company — see the Error Log lines above")
		#//// Neoffice — removed the CI diagnostic block (companies print + manual
		#//// make_test_records("Company") savepoint/rollback dry run) (3638cec52 "test(payroll):
		#//// break the Company -> Swiss Social Insurance Config -> Account cycle in test records"):
		#//// root cause found (Company -> Swiss Social Insurance Config -> Account/Salary Component
		#//// cycle in test records) and fixed by ignoring those doctypes in the Swiss config test
		#//// module too, so the diagnostics are no longer needed.

	enable_all_roles_and_domains()
	set_defaults()
	frappe.db.commit()  # nosemgrep
	_diag_records()


def _instrumented_make_test_objects(doctype, test_records=None, verbose=None, reset=False, commit=False):
	from frappe.model.naming import revert_series_if_last

	records = []
	if test_records is None:
		test_records = frappe.get_test_records(doctype)
	print(f"RECSPY {doctype}: {len(test_records or [])} record(s), commit={commit} reset={reset}", flush=True)
	for doc in test_records:
		if not doc.get("doctype"):
			doc["doctype"] = doctype
		d = frappe.copy_doc(doc)
		if d.meta.get_field("naming_series") and not d.naming_series:
			d.naming_series = "_T-" + d.doctype + "-"
		if doc.get("name"):
			d.name = doc.get("name")
		else:
			d.set_new_name()
		exists = frappe.db.exists(d.doctype, d.name)
		print(f"RECSPY   {doctype} candidate={d.name} exists={bool(exists)}", flush=True)
		if exists and not reset:
			print(f"RECSPY   {doctype} SKIP + ROLLBACK on {d.name}", flush=True)
			frappe.db.rollback()
			continue
		docstatus = d.docstatus
		d.docstatus = 0
		try:
			d.run_method("before_test_insert")
			d.insert(ignore_if_duplicate=True)
			if docstatus == 1:
				d.submit()
			print(f"RECSPY   {doctype} INSERTED {d.name}", flush=True)
		except frappe.NameError as exc:
			print(f"RECSPY   {doctype} NameError on {d.name}: {exc}", flush=True)
			if getattr(d, "naming_series", None):
				revert_series_if_last(d.naming_series, d.name)
		except Exception as exc:
			swallowed = bool(d.flags.ignore_these_exceptions_in_test) and exc.__class__ in (
				d.flags.ignore_these_exceptions_in_test or []
			)
			print(
				f"RECSPY   {doctype} {type(exc).__name__} on {d.name} swallowed={swallowed}: {str(exc)[:400]}",
				flush=True,
			)
			if swallowed:
				if getattr(d, "naming_series", None):
					revert_series_if_last(d.naming_series, d.name)
			else:
				raise
		records.append(d.name)
		if commit:
			frappe.db.commit()
	return records


def _diag_records():
	# DIAGNOSTIC ONLY (branch ci/diag-commit-spy)
	import frappe.test_runner as tr

	original = tr.make_test_objects

	def spy(doctype, test_records=None, verbose=None, reset=False, commit=False):
		if doctype in ("Employee", "Shift Type"):
			return _instrumented_make_test_objects(
				doctype, test_records=test_records, verbose=verbose, reset=reset, commit=commit
			)
		return original(doctype, test_records=test_records, verbose=verbose, reset=reset, commit=commit)

	tr.make_test_objects = spy

	print("DIAG users:", frappe.get_all("User", pluck="name"), flush=True)
	tr.make_test_records("Employee", verbose=0, commit=True)
	tr.make_test_records_for_doctype("Employee", verbose=0, commit=True)
	print("DIAG employees:", frappe.get_all("Employee", pluck="name"), flush=True)
	tr.make_test_records("Shift Type", verbose=0, commit=True)
	tr.make_test_records_for_doctype("Shift Type", verbose=0, commit=True)
	print("DIAG shift types:", frappe.get_all("Shift Type", pluck="name"), flush=True)


def set_defaults():
	from hrms.payroll.doctype.salary_slip.test_salary_slip import make_holiday_list

	make_holiday_list("Salary Slip Test Holiday List")
	frappe.db.set_value("Company", "_Test Company", "default_holiday_list", "Salary Slip Test Holiday List")


def get_first_sunday(holiday_list="Salary Slip Test Holiday List", for_date=None, find_after_for_date=False):
	date = for_date or getdate()
	month_start_date = get_first_day(date)

	if find_after_for_date:
		# explictly find first sunday after for_date
		# useful when DOJ is after the month start
		month_start_date = date

	month_end_date = get_last_day(date)
	first_sunday = frappe.db.sql(
		"""
		select holiday_date from `tabHoliday`
		where parent = %s
			and holiday_date between %s and %s
		order by holiday_date
	""",
		(holiday_list, month_start_date, month_end_date),
	)[0][0]

	return first_sunday


def get_first_day_for_prev_month():
	prev_month = add_months(getdate(), -1)
	prev_month_first = prev_month.replace(day=1)
	return prev_month_first


def add_date_to_holiday_list(date: str, holiday_list: str) -> None:
	if frappe.db.exists("Holiday", {"parent": holiday_list, "holiday_date": date}):
		return

	holiday_list = frappe.get_doc("Holiday List", holiday_list)
	holiday_list.append(
		"holidays",
		{
			"holiday_date": date,
			"description": "test",
		},
	)
	holiday_list.save()


def create_company(name: str = "_Test Company", is_group: 0 | 1 = 0, parent_company: str | None = None):
	if frappe.db.exists("Company", name):
		return frappe.get_doc("Company", name)

	return frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": name,
			"default_currency": "INR",
			"country": "India",
			"is_group": is_group,
			"parent_company": parent_company,
		}
	).insert()


def create_department(name: str, company: str = "_Test Company") -> str:
	docname = get_abbreviated_name(name, company)

	if frappe.db.exists("Department", docname):
		return docname

	department = frappe.new_doc("Department")
	department.update({"doctype": "Department", "department_name": name, "company": "_Test Company"})
	department.insert()
	return department.name


def create_employee_grade(grade: str, default_structure: str | None = None, default_base: float = 50000):
	if frappe.db.exists("Employee Grade", grade):
		return frappe.get_doc("Employee Grade", grade)
	return frappe.get_doc(
		{
			"doctype": "Employee Grade",
			"__newname": grade,
			"default_salary_structure": default_structure,
			"default_base_pay": default_base,
		}
	).insert()


def create_job_applicant(**args):
	args = frappe._dict(args)
	filters = {
		"applicant_name": args.applicant_name or "_Test Applicant",
		"email_id": args.email_id or "test_applicant@example.com",
	}

	if frappe.db.exists("Job Applicant", filters):
		return frappe.get_doc("Job Applicant", filters)

	job_applicant = frappe.get_doc(
		{
			"doctype": "Job Applicant",
			"status": args.status or "Open",
			"designation": create_designation().name,
		}
	)
	job_applicant.update(filters)
	job_applicant.save()
	return job_applicant


def get_email_by_subject(subject: str) -> str | None:
	return frappe.db.exists("Email Queue", {"message": ("like", f"%{subject}%")})
