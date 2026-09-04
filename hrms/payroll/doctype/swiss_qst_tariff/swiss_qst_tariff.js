//// Neoffice — added file (no upstream equivalent): desk form of Swiss QST Tariff (import the
//// ESTV tariff file, browse brackets).
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Swiss QST Tariff", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Import from File"), function () {
				frappe.confirm(
					__("This will delete existing brackets and re-import from the attached file. Continue?"),
					function () {
						frappe.call({
							method: "import_from_file",
							doc: frm.doc,
							freeze: true,
							freeze_message: __("Importing tariff brackets..."),
							callback: function () {
								frm.reload_doc();
							},
						});
					}
				);
			}, __("Actions"));

			frm.add_custom_button(__("Fetch from ESTV"), function () {
				frappe.confirm(
					__("This will download tariff data from ESTV and import brackets. Continue?"),
					function () {
						frappe.call({
							method: "fetch_from_estv",
							doc: frm.doc,
							freeze: true,
							freeze_message: __("Downloading from ESTV..."),
							callback: function () {
								frm.reload_doc();
							},
						});
					}
				);
			}, __("Actions"));

			if (frm.doc.status !== "Active" && frm.doc.record_count > 0) {
				frm.add_custom_button(__("Activate"), function () {
					frappe.call({
						method: "activate",
						doc: frm.doc,
						callback: function () {
							frm.reload_doc();
						},
					});
				}).addClass("btn-primary");
			}
		}
	},
});

// List view action: Fetch All Cantons
frappe.listview_settings["Swiss QST Tariff"] = {
	onload: function (listview) {
		listview.page.add_inner_button(__("Fetch All Cantons"), function () {
			let year = new Date().getFullYear();
			let d = new frappe.ui.Dialog({
				title: __("Fetch All Cantons from ESTV"),
				fields: [
					{
						label: __("Year"),
						fieldname: "year",
						fieldtype: "Int",
						default: year,
						reqd: 1,
					},
					{
						label: __("Tariff Type"),
						fieldname: "tariff_type",
						fieldtype: "Select",
						options: "Salaires\nAutres revenus",
						default: "Salaires",
						reqd: 1,
					},
				],
				primary_action_label: __("Fetch"),
				primary_action(values) {
					frappe.call({
						method: "hrms.payroll.doctype.swiss_qst_tariff.swiss_qst_tariff.fetch_all_cantons",
						args: {
							year: values.year,
							tariff_type: values.tariff_type,
						},
						callback: function () {
							listview.refresh();
						},
					});
					d.hide();
				},
			});
			d.show();
		});
	},
	get_indicator: function (doc) {
		if (doc.status === "Active") {
			return [__("Active"), "green", "status,=,Active"];
		} else if (doc.status === "Archived") {
			return [__("Archived"), "grey", "status,=,Archived"];
		}
		return [__("Draft"), "orange", "status,=,Draft"];
	},
};
