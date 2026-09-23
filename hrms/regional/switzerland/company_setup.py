# //// Neoffice — added file (no upstream equivalent): server side of the company payroll setup
# //// wizard (desk page swiss-company-payroll-setup), the first step of the Swiss payroll
# //// onboarding.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""The questions a Swiss company answers once, before its first payroll run.

Until 2026-09-23 the onboarding asked none of them. The booking method, the third-party
allowances, the salary payment account and the contact of the salary certificate were left at
their defaults on the Company form, which no onboarding step opens, and no social insurance
configuration was ever marked as the default one — so the first monthly cycle stopped on
"no configuration". The wizard reads the current values and proposes what the chart of accounts
and the company address already say, so it is also the place to change these choices later.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint

from hrms.regional.switzerland import accounting

# Written on the Company.
COMPANY_FIELDS = (
	"ch_uid_bfs",
	"ch_contact_person",
	"ch_contact_phone",
	"ch_contact_email",
	"ch_payroll_booking_method",
	"ch_third_party_allowance_booking",
	"ch_third_party_allowance_account",
	"default_payroll_payable_account",
)
# Written on the company's default Swiss Social Insurance Config.
CONFIG_FIELDS = (
	"avs_admin_fee_rate",
	"laa_professional_rate",
	"laa_nonprofessional_rate",
	"ijm_rate_employee",
	"ijm_rate_employer",
	"laac_rate_employee",
	"laac_rate_employer",
	"family_allowance_rate",
	"lpp_employer_share_pct",
	"thirteenth_month_mode",
	"qst_enabled",
	"qst_default_canton",
	"lohnausweis_employer_name",
	"lohnausweis_employer_address",
	"lohnausweis_expense_regulation_canton",
	"lohnausweis_expense_regulation_date",
	"payment_account",
	"payment_iban",
	"payment_bic",
)
ACCOUNT_FIELDS = ("ch_third_party_allowance_account", "default_payroll_payable_account", "payment_account")
DEFAULTS = {
	"ch_payroll_booking_method": accounting.BOOKING_LIABILITY,
	"ch_third_party_allowance_booking": accounting.THIRD_PARTY_SALARIES,
	"lpp_employer_share_pct": 50,
	"thirteenth_month_mode": "Disabled",
	"configure_accounts": 1,
}


def _check_permissions(company, write=False):
	frappe.has_permission("Company", "write" if write else "read", doc=company, throw=True)
	frappe.has_permission("Swiss Social Insurance Config", "write" if write else "read", throw=True)


def _default_config(company):
	return frappe.db.get_value(
		"Swiss Social Insurance Config", {"company": company, "is_default": 1}, "name"
	) or frappe.db.get_value("Swiss Social Insurance Config", {"company": company}, "name")


def _company_address(company):
	"""The company's own address as the certificate prints it: street, then ZIP and city."""
	address = frappe.db.sql(
		"""SELECT a.address_line1, a.address_line2, a.pincode, a.city
		FROM `tabAddress` a JOIN `tabDynamic Link` dl ON dl.parent = a.name AND dl.parenttype = 'Address'
		WHERE dl.link_doctype = 'Company' AND dl.link_name = %s AND COALESCE(a.disabled, 0) = 0
		ORDER BY a.is_your_company_address DESC, a.is_primary_address DESC, a.modified DESC LIMIT 1""",
		company,
		as_dict=True,
	)
	if not address:
		return ""
	row = address[0]
	lines = [row.address_line1, row.address_line2, " ".join(filter(None, (row.pincode, row.city)))]
	return "\n".join(line for line in lines if line)


@frappe.whitelist()
def get_company_setup(company):
	"""The current answers of ``company``, and a proposal for those still empty."""
	_check_permissions(company)
	values = frappe._dict(frappe.db.get_value("Company", company, list(COMPANY_FIELDS), as_dict=True) or {})
	values.company = company
	config = _default_config(company)
	if config:
		values.update(
			frappe.db.get_value(
				"Swiss Social Insurance Config", config, ["canton", *CONFIG_FIELDS], as_dict=True
			)
			or {}
		)
	values.config = config

	proposed = {}
	accounts = accounting._company_accounts(company)
	if not values.get("default_payroll_payable_account"):
		proposed["default_payroll_payable_account"] = accounting.pick_account(accounts, "payroll_payable")
	if not values.get("ch_third_party_allowance_account"):
		proposed["ch_third_party_allowance_account"] = accounting.pick_account(
			accounts, "receivable_insurance"
		)
	if not values.get("payment_account"):
		proposed["payment_account"] = frappe.db.get_value("Company", company, "default_bank_account")
	if not values.get("lohnausweis_employer_name"):
		proposed["lohnausweis_employer_name"] = frappe.db.get_value("Company", company, "company_name")
	if not values.get("lohnausweis_employer_address"):
		proposed["lohnausweis_employer_address"] = _company_address(company)
	for field, value in {**DEFAULTS, **proposed}.items():
		if value and not values.get(field):
			values[field] = value
	values.proposed = sorted(field for field, value in proposed.items() if value)
	return values


@frappe.whitelist(methods=["POST"])
def apply_company_setup(data):
	"""Write the answers: the Company's payroll fields, then its default social insurance
	configuration (created for the canton when missing), then — if asked — the payroll accounts
	from the chart (accounting.configure_payroll_accounts, which never overwrites)."""
	data = frappe._dict(json.loads(data) if isinstance(data, str) else data)
	company = data.get("company")
	if not company or not data.get("canton"):
		frappe.throw(_("Company and canton are required."))
	_check_permissions(company, write=True)

	for field in ACCOUNT_FIELDS:
		account = data.get(field)
		if account and frappe.db.get_value("Account", account, "company") != company:
			frappe.throw(_("Account {0} does not belong to {1}.").format(account, company))
	if data.get("ch_third_party_allowance_booking") not in (
		accounting.THIRD_PARTY_SALARIES,
		accounting.THIRD_PARTY_RECEIVABLE,
	):
		data.ch_third_party_allowance_booking = accounting.THIRD_PARTY_SALARIES
	if data.get("ch_payroll_booking_method") not in (
		accounting.BOOKING_LIABILITY,
		accounting.BOOKING_CHARGES,
	):
		data.ch_payroll_booking_method = accounting.BOOKING_LIABILITY

	# Only what the wizard sent: a field it does not know stays as it is.
	frappe.db.set_value("Company", company, {field: data[field] for field in COMPANY_FIELDS if field in data})

	name = frappe.db.get_value(
		"Swiss Social Insurance Config", {"company": company, "canton": data.canton}, "name"
	)
	if name:
		config = frappe.get_doc("Swiss Social Insurance Config", name)
	else:
		# A new canton: start from the company's current default so its other settings follow.
		config = frappe.new_doc("Swiss Social Insurance Config")
		current = _default_config(company)
		if current:
			source = frappe.get_doc("Swiss Social Insurance Config", current)
			config.update(
				{
					key: value
					for key, value in source.as_dict(no_default_fields=True).items()
					if key not in ("is_default", "canton") and not isinstance(value, list)
				}
			)
		config.company = company
		config.canton = data.canton
	config.update({field: data[field] for field in CONFIG_FIELDS if field in data})
	if "qst_enabled" in data:
		config.qst_enabled = cint(data.qst_enabled)
	config.is_default = 1
	config.save()
	frappe.db.set_value("Company", company, "ch_default_social_insurance_config", config.name)

	result = {"config": config.name}
	if cint(data.get("configure_accounts")):
		result["accounts"] = accounting.configure_payroll_accounts(company)
	# Each company its own Swiss salary structure, submitted: the employee wizard assigns it.
	from hrms.regional.switzerland.setup import ensure_company_salary_structure

	result["salary_structure"] = ensure_company_salary_structure(company)
	return result
