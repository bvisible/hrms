//// Neoffice — added file (no upstream equivalent): desk form of Swiss Wage Type — creates the
//// matching Salary Component(s) from a catalog code.
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Swiss Wage Type", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Create Salary Component(s)"), () => {
				frappe.call({
					method: "hrms.regional.switzerland.api.create_salary_component_from_wage_type",
					args: { wage_type_code: frm.doc.code },
					freeze: true,
					freeze_message: __("Creating Salary Component(s)..."),
					callback(r) {
						if (r.message) {
							let primary = r.message.primary;
							let linked = r.message.linked;
							if (linked) {
								frappe.show_alert({
									message: __("Created {0} and {1} (linked pair)", [primary, linked]),
									indicator: "green",
								});
							} else {
								frappe.show_alert({
									message: __("Created {0}", [primary]),
									indicator: "green",
								});
							}
							frappe.set_route("Form", "Salary Component", primary);
						}
					},
				});
			});

			// Show indicator for employer contribution
			if (frm.doc.is_employer_contribution) {
				frm.dashboard.set_headline(
					__('<span class="indicator-pill orange">{0}</span>', [__("Employer Contribution")])
				);
			}
		}
	},
});
