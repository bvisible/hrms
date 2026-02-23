// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Swiss Wage Type", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Create Salary Component"), () => {
				frappe.call({
					method: "hrms.regional.switzerland.api.create_salary_component_from_wage_type",
					args: { wage_type_code: frm.doc.code },
					freeze: true,
					freeze_message: __("Creating Salary Component..."),
					callback(r) {
						if (r.message) {
							frappe.set_route("Form", "Salary Component", r.message);
							frappe.show_alert({
								message: __("Salary Component {0} created", [r.message]),
								indicator: "green",
							});
						}
					},
				});
			});
		}
	},
});
