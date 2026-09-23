//// Neoffice — added file (no upstream equivalent): the form of a Swiss insurer statement.
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Swiss Insurer Statement", {
	setup(frm) {
		frm.set_query("paid_from", () => ({
			filters: {
				company: frm.doc.company,
				is_group: 0,
				account_type: ["in", ["Bank", "Cash"]],
			},
		}));
	},

	refresh(frm) {
		// A statement opened prefilled (year-end closing) has its lines but not yet their total.
		if (frm.is_new() && (frm.doc.lines || []).length && !frm.doc.total) {
			update_total(frm);
		}
		if (frm.doc.docstatus === 1 && frm.doc.journal_entry) {
			frm.add_custom_button(__("Journal Entry"), () =>
				frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry)
			);
		}
		if (frm.doc.company) {
			frm.add_custom_button(__("Reconciliation"), () =>
				frappe.set_route("query-report", "Swiss Social Insurance Reconciliation", {
					company: frm.doc.company,
				})
			);
		}
	},

	// The insurances an insurer usually invoices: those of its last statement.
	insurer(frm) {
		if (!frm.doc.insurer || !frm.doc.company || (frm.doc.lines || []).some((line) => line.insurance)) {
			return;
		}
		frappe
			.call({
				method: "hrms.regional.switzerland.insurer_statements.statement_defaults",
				args: { company: frm.doc.company, insurer: frm.doc.insurer },
			})
			.then((r) => {
				const insurances = (r.message && r.message.insurances) || [];
				if (!insurances.length) {
					return;
				}
				frm.clear_table("lines");
				insurances.forEach((insurance) => frm.add_child("lines", { insurance }));
				frm.refresh_field("lines");
			});
	},
});

frappe.ui.form.on("Swiss Insurer Statement Line", {
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
