//// Neoffice — added file (no upstream equivalent): the form of a Swiss payroll accrual.
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Swiss Payroll Accrual", {
	setup(frm) {
		const accounts = () => ({ filters: { company: frm.doc.company, is_group: 0 } });
		frm.set_query("accrual_account", accounts);
		frm.set_query("account", "lines", accounts);
	},

	refresh(frm) {
		if (frm.is_new() && (frm.doc.lines || []).length && !frm.doc.total) {
			update_total(frm);
		}
		if (frm.doc.docstatus !== 1) {
			return;
		}
		if (frm.doc.journal_entry) {
			frm.add_custom_button(__("Journal Entry"), () =>
				frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry)
			);
		}
		if (frm.doc.reversal_entry) {
			frm.add_custom_button(__("Reversal Entry"), () =>
				frappe.set_route("Form", "Journal Entry", frm.doc.reversal_entry)
			);
		} else if (frm.doc.reversal_date) {
			frm.add_custom_button(__("Create the Reversal"), () =>
				frm.call("make_reversal").then(() => frm.reload_doc())
			);
		}
	},

	// The year's last day for the accrual, the next year's first for its reversal.
	async fiscal_year(frm) {
		if (!frm.doc.fiscal_year) {
			return;
		}
		const fy = (await frappe.db.get_value("Fiscal Year", frm.doc.fiscal_year, "year_end_date")).message;
		if (fy && fy.year_end_date) {
			frm.set_value("posting_date", fy.year_end_date);
			frm.set_value("reversal_date", frappe.datetime.add_days(fy.year_end_date, 1));
		}
	},
});

frappe.ui.form.on("Swiss Payroll Accrual Line", {
	amount(frm) {
		update_total(frm);
	},
	lines_remove(frm) {
		update_total(frm);
	},
});

function update_total(frm) {
	const total = (frm.doc.lines || []).reduce((sum, line) => sum + flt(line.amount, 2), 0);
	frm.set_value("total", flt(total, 2));
}
