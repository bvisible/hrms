// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Swiss Salary Certificate", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.employee && frm.doc.fiscal_year) {
			frm.add_custom_button(__("Populate from Salary Slips"), function () {
				frm.call("populate_from_salary_slips").then(() => {
					frm.refresh_fields();
				});
			});
		}
	},
});
