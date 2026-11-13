//// Neoffice — added file (no upstream equivalent): the list of the labour agreements opens on the templates
//// (lot T, neoffice-maintenance#2623): a new agreement starts from a dated and sourced template, or empty.
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.listview_settings["Labour Agreement"] = {
	onload(list) {
		if (frappe.model.can_create("Labour Agreement")) {
			list.page.add_inner_button(__("Use a template"), () => {
				frappe.model.with_doctype("Labour Agreement", () => {
					frappe.new_doc("Labour Agreement");
				});
			});
		}
	},
};
