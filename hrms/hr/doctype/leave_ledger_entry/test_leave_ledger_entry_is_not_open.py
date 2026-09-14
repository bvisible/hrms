# //// Neoffice — added file (no upstream equivalent), neoffice-maintenance#432: Leave Ledger Entry
# //// must not be open to every account. Upstream grants All create, write, submit and delete on
# //// one's own entries; a portal account could forge lines of any employee's leave balance.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import json
import os
import unittest

DOCTYPE_JSON = os.path.join(os.path.dirname(__file__), "leave_ledger_entry.json")


class TestTheDocTypeIsNotOpen(unittest.TestCase):
	def test_no_row_for_all_or_guest(self):
		with open(DOCTYPE_JSON, encoding="utf8") as f:
			perms = json.load(f)["permissions"]
		self.assertFalse([p for p in perms if p.get("role") in ("All", "Guest")])
		self.assertEqual({p["role"] for p in perms}, {"System Manager", "HR Manager", "HR User"})
