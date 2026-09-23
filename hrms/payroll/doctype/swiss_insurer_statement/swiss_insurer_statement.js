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

	canton(frm) {
		update_commission(frm);
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
	amount(frm, cdt, cdn) {
		if (locals[cdt][cdn].insurance === "Source Tax") {
			update_commission(frm);
		}
		update_total(frm);
	},
	insurance(frm, cdt, cdn) {
		if (locals[cdt][cdn].insurance === "Source Tax") {
			update_commission(frm);
		}
	},
	lines_remove(frm) {
		update_total(frm);
	},
});

function update_total(frm) {
	const total = (frm.doc.lines || []).reduce((sum, line) => sum + flt(line.amount, 2), 0);
	frm.set_value("total", flt(total, 2));
}

// The collection commission the canton leaves the employer on the source tax: the canton's rate
// (ESTV table) applied to the source tax lines, as a negative line credited to an income. Editable:
// the canton's own statement has the last word.
async function update_commission(frm) {
	const source_tax = (frm.doc.lines || [])
		.filter((line) => line.insurance === "Source Tax")
		.reduce((sum, line) => sum + flt(line.amount, 2), 0);
	if (!frm.doc.canton || !source_tax) {
		return;
	}
	const rate = (
		await frappe.call({
			method: "hrms.regional.switzerland.insurer_statements.get_source_tax_commission_rate",
			args: { canton: frm.doc.canton },
		})
	).message;
	if (!rate) {
		return;
	}
	let line = (frm.doc.lines || []).find((row) => row.insurance === "Source Tax Commission");
	if (!line) {
		line = frm.add_child("lines", { insurance: "Source Tax Commission" });
	}
	frappe.model.set_value(line.doctype, line.name, "amount", -flt((source_tax * rate) / 100, 2));
	frappe.model.set_value(
		line.doctype,
		line.name,
		"description",
		__("Collection commission {0} %", [rate])
	);
	frm.refresh_field("lines");
	update_total(frm);
}

