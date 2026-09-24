// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Employee", {
	refresh: function (frm) {
		frm.set_query("payroll_cost_center", function () {
			return {
				filters: {
					company: frm.doc.company,
					is_group: 0,
				},
			};
		});

		// hide naming series field based on hr settings
		//// Neoffice — silent: HR Settings may be closed to the HR staff (a Custom DocPerm keeps it
		//// to the administrators), and frappe.db.get_single_value then opened « No permission for
		//// HR Settings » on every employee they opened. Unreadable, the naming series keeps its
		//// default display.
		frappe.call({
			method: "frappe.client.get_single_value",
			args: { doctype: "HR Settings", field: "emp_created_by" },
			silent: true,
			callback: (r) => frm.toggle_display("naming_series", r.message === "Naming Series"),
		});
	},

	date_of_birth(frm) {
		frm.call({
			method: "hrms.overrides.employee_master.get_retirement_date",
			args: {
				date_of_birth: frm.doc.date_of_birth,
			},
		}).then((r) => {
			if (r && r.message) frm.set_value("date_of_retirement", r.message);
		});
	},
});
