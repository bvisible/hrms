# //// Neoffice — added file (no upstream equivalent): the Swiss social insurance config is ours.
# Copyright (c) 2026, Neoffice and Contributors
# See license.txt

from frappe.tests.utils import FrappeTestCase

# Company carries our custom Link field `ch_default_social_insurance_config`, so the test
# runner walks Company -> Swiss Social Insurance Config -> Account | Salary Component while
# making Company's own test records. erpnext's Company test module ignores those doctypes
# for exactly that cycle (test_ignore), but frappe applies test_ignore per module, not
# transitively: Account test records were created before `_Test Company 1` existed and
# Account.autoname died on a None abbreviation (CI, 2026-09-04, tracker #203).
test_ignore = ["Account", "Salary Component", "Company"]


class TestSwissSocialInsuranceConfig(FrappeTestCase):
	pass
