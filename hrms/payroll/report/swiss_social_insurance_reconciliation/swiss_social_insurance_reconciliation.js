//// Neoffice — added file (no upstream equivalent): filters and status colours of the yearly
//// reconciliation of the Swiss payroll's insurance accounts.
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.query_reports["Swiss Social Insurance Reconciliation"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "fiscal_year",
			label: __("Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			default: frappe.defaults.get_user_default("fiscal_year"),
			reqd: 1,
		},
	],

	onload(report) {
		report.page.add_inner_button(__("New Insurer Statement"), () =>
			frappe.new_doc("Swiss Insurer Statement", { company: report.get_filter_value("company") })
		);
	},

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "status" && data) {
			const colour = {
				balanced: "green",
				final_statement_missing: "orange",
				difference: "red",
				no_activity: "gray",
			}[data.status_key];
			return `<span class="indicator-pill ${colour}">${value}</span>`;
		}
		return value;
	},
};
