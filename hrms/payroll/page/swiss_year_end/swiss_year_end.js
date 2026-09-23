//// Neoffice — added file (no upstream equivalent): desk page driving the Swiss year-end closing
//// (reconcile, batch certificates, per-canton source-tax recap).
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.pages["swiss-year-end"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Swiss Year-End Closing"),
		single_column: true,
	});
	wrapper.closing = new SwissYearEnd(page);
};

class SwissYearEnd {
	constructor(page) {
		this.page = page;
		this.state = {};
		this.make_filters();
		this.body = $('<div style="padding: 15px 0;"></div>').appendTo(this.page.main);
		this.body.html(
			`<div class="text-muted" style="padding: 40px; text-align: center;">
				${__("Pick a company and a fiscal year, then run the reconciliation.")}
			</div>`,
		);
	}

	make_filters() {
		this.company_field = this.page.add_field({
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		});
		this.year_field = this.page.add_field({
			fieldname: "fiscal_year",
			label: __("Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			default: frappe.defaults.get_user_default("fiscal_year"),
			reqd: 1,
		});
		this.page.set_primary_action(__("Reconcile"), () => this.run_reconcile(), "search");
	}

	args() {
		return {
			company: this.company_field.get_value(),
			fiscal_year: this.year_field.get_value(),
		};
	}

	async call(method, extra = {}) {
		const r = await frappe.call({
			method: `hrms.regional.switzerland.year_end.${method}`,
			args: { ...this.args(), ...extra },
			freeze: true,
			freeze_message: __("Working..."),
		});
		return r.message;
	}

	async run_reconcile() {
		if (!this.company_field.get_value() || !this.year_field.get_value()) {
			frappe.msgprint(__("Please select a company and a fiscal year"));
			return;
		}
		this.state.reconcile = await this.call("reconcile");
		this.state.qst = await this.call("qst_summary");
		//// Neoffice — the insurance accounts, for whoever may read the ledger (the reconciliation
		//// reads it; an HR user without accounting access simply does not get the card).
		this.state.insurance = frappe.model.can_read("GL Entry")
			? (
					await frappe.call({
						method: "hrms.regional.switzerland.insurer_statements.reconcile",
						args: this.args(),
					})
				).message
			: null;
		this.render();
	}

	//// Neoffice — the final statement of an account, in one gesture: the insurer last used for it,
	//// the fiscal year as period, and what is left to settle as amount.
	async record_statement(row) {
		const args = this.args();
		const insurance = row.insurances[0];
		const [period_from, period_to] = this.state.insurance.period;
		let amount = row.suggested;
		let canton = "";
		let rate = null;
		// The source tax: one statement per canton — each invoices its own tax and leaves its own
		// collection commission. Several cantons still open: the user picks one.
		if (insurance === "Source Tax") {
			const cantons = (
				(
					await frappe.call({
						method: "hrms.regional.switzerland.insurer_statements.source_tax_cantons",
						args,
					})
				).message || []
			).filter((c) => Math.abs(c.remaining) >= 0.5);
			const choice = cantons.length > 1 ? await pick_canton(cantons) : cantons[0];
			if (cantons.length > 1 && !choice) {
				return;
			}
			if (choice) {
				({ canton, rate } = choice);
				amount = choice.remaining;
			}
		}
		const defaults =
			(
				await frappe.call({
					method: "hrms.regional.switzerland.insurer_statements.statement_defaults",
					args: { company: args.company, insurance, canton },
				})
			).message || {};
		frappe.new_doc("Swiss Insurer Statement", {}, (doc) => {
			Object.assign(doc, {
				company: args.company,
				kind: "Final Statement",
				period_from,
				period_to,
				canton,
				insurer: defaults.insurer || "",
			});
			// The lines table is mandatory: a new document already carries an empty row.
			const empty = (doc.lines || []).find((line) => !line.insurance);
			const line =
				empty || frappe.model.add_child(doc, "Swiss Insurer Statement Line", "lines");
			line.insurance = insurance;
			line.amount = amount;
			if (rate) {
				const commission = frappe.model.add_child(
					doc,
					"Swiss Insurer Statement Line",
					"lines",
				);
				commission.insurance = "Source Tax Commission";
				commission.amount = -flt((amount * rate) / 100, 2);
				commission.description = __("Collection commission {0} %", [rate]);
			}
		});
	}

	//// Neoffice — the year-end accruals (transitoires): under the social charges method, the
	//// employer charges the slips computed and no statement charged yet; bonuses are added by hand.
	async record_accruals() {
		const args = this.args();
		const proposal = (
			await frappe.call({
				method: "hrms.regional.switzerland.insurer_statements.accrual_proposals",
				args,
			})
		).message;
		frappe.new_doc("Swiss Payroll Accrual", {}, (doc) => {
			Object.assign(doc, {
				company: args.company,
				fiscal_year: args.fiscal_year,
				posting_date: proposal.posting_date,
				reversal_date: proposal.reversal_date,
			});
			proposal.lines.forEach((values, index) => {
				const empty = index === 0 && (doc.lines || []).find((line) => !line.account);
				const line =
					empty || frappe.model.add_child(doc, "Swiss Payroll Accrual Line", "lines");
				Object.assign(line, values);
			});
		});
	}

	render_insurance() {
		const ins = this.state.insurance;
		if (!ins || !ins.rows.length) {
			return "";
		}
		const badge = {
			balanced: `<span class="indicator-pill green" style="white-space: nowrap;">${__("Account settled")}</span>`,
			payroll_not_booked: `<span class="indicator-pill yellow" style="white-space: nowrap;">${__("Payroll not booked")}</span>`,
			final_statement_missing: `<span class="indicator-pill orange" style="white-space: nowrap;">${__("Final statement missing")}</span>`,
			difference: `<span class="indicator-pill red" style="white-space: nowrap;">${__("Difference to explain")}</span>`,
			no_activity: `<span class="indicator-pill gray" style="white-space: nowrap;">${__("No activity")}</span>`,
		};
		const rows = ins.rows
			.map(
				(r, index) => `
				<tr>
					<td>${r.insurances.map((label) => frappe.utils.escape_html(__(label))).join(", ")}</td>
					<td><a href="/app/account/${encodeURIComponent(r.account)}">${frappe.utils.escape_html(r.account)}</a></td>
					<td class="text-right">${format_currency(r.side === "charge" ? r.employer_due : r.due, "CHF")}</td>
					<td class="text-right">${format_currency(r.statements + r.after, "CHF")}</td>
					<td class="text-right">${format_currency(r.balance, "CHF")}</td>
					<td>${badge[r.status] || ""}</td>
					<td class="text-right">${
						["final_statement_missing", "difference"].includes(r.status) &&
						Math.abs(r.suggested) >= 0.5
							? `<button class="btn btn-xs btn-default btn-record-statement" data-index="${index}">
									${__("Record the final statement")}</button>`
							: ""
					}</td>
				</tr>`,
			)
			.join("");
		const method =
			ins.method === "Social Charges"
				? __(
						"Social charges method: the statements are charged, the employer part is what remains.",
					)
				: __(
						"Current account method: after the final statement, each account is back to zero.",
					);
		return `
			<div class="frappe-card" style="padding: 15px; margin-bottom: 15px;">
				<h5>${__("Social insurance accounts")}</h5>
				<p class="text-muted small">${method}
					${ins.unbooked_slips ? " " + __("{0} slip(s) of the year not booked yet.", [ins.unbooked_slips]) : ""}</p>
				<div style="overflow-x: auto;">
					<table class="table table-sm">
						<thead><tr>
							<th>${__("Insurances")}</th><th>${__("Account")}</th>
							<th class="text-right">${__("Due per payroll")}</th>
							<th class="text-right">${__("Statements")}</th>
							<th class="text-right">${__("Balance to settle")}</th>
							<th>${__("Status")}</th><th></th>
						</tr></thead>
						<tbody>${rows}</tbody>
					</table>
				</div>
			</div>`;
	}

	async run_generate() {
		const res = await this.call("generate_certificates");
		let message = __("{0} certificate(s) created, {1} skipped", [
			res.created.length,
			res.skipped.length,
		]);
		if (res.failed.length) {
			message += "<br><b>" + __("{0} failed", [res.failed.length]) + "</b>";
			res.failed.forEach((f) => {
				//// Neoffice — f.error was interpolated raw into an HTML msgprint. It is the last
				//// line of a server traceback, which quotes document content (an employee name, a
				//// validation message) — i.e. text a user can influence. Escaped like f.employee.
				message += `<br>${frappe.utils.escape_html(f.employee)}: ${frappe.utils.escape_html(f.error)}`;
			});
		}
		frappe.msgprint({
			title: __("Certificates"),
			message: message,
			indicator: res.failed.length ? "orange" : "green",
		});
		await this.run_reconcile();
	}

	//// Neoffice — validate the drafts (each gets its Swissdec DocID), then mail the validated
	//// certificates to the employees: the two steps that closed the year one form at a time.
	async run_submit() {
		const res = await this.call("submit_certificates");
		let message = __("{0} certificate(s) validated", [res.submitted.length]);
		res.failed.forEach((f) => {
			message += `<br>${frappe.utils.escape_html(f.certificate)}: ${frappe.utils.escape_html(f.error)}`;
		});
		frappe.msgprint({
			title: __("Certificates"),
			message: message,
			indicator: res.failed.length ? "orange" : "green",
		});
		await this.run_reconcile();
	}

	run_send(count) {
		frappe.confirm(
			__("Send {0} salary certificate(s) to the employees by email?", [count]),
			async () => {
				const res = await this.call("send_certificates");
				let message = __(
					"{0} email(s) are being sent. You will be told when they are out.",
					[res.queued],
				);
				if (res.without_email.length) {
					message +=
						"<br>" +
						__("No email address: {0}", [
							res.without_email.map((n) => frappe.utils.escape_html(n)).join(", "),
						]);
				}
				frappe.msgprint({
					title: __("Certificates"),
					message: message,
					indicator: "blue",
				});
			},
		);
	}

	render() {
		const rec = this.state.reconcile;
		const parts = [];

		if (rec.issues && rec.issues.length) {
			const pills = rec.issues
				.map(
					(i) => `
					<div class="indicator-pill ${i.level === "error" ? "red" : "orange"}" style="margin: 2px 6px 2px 0;">
						${frappe.utils.escape_html(i.message)}
					</div>`,
				)
				.join("");
			parts.push(`
				<div class="frappe-card" style="padding: 15px; margin-bottom: 15px;">
					<h5>${__("Checks")}</h5>
					<div style="display: flex; flex-wrap: wrap;">${pills}</div>
				</div>`);
		}

		const cert_badge = {
			missing: `<span class="indicator-pill red">${__("missing")}</span>`,
			draft: `<span class="indicator-pill orange">${__("draft")}</span>`,
			submitted: `<span class="indicator-pill blue">${__("validated")}</span>`,
			sent: `<span class="indicator-pill green">${__("sent")}</span>`,
		};
		const rows = (rec.employees || [])
			.map(
				(e) => `
				<tr>
					<td>${frappe.utils.escape_html(e.employee_name)}</td>
					<td class="text-center">${e.slips}</td>
					<td class="text-right">${format_currency(e.gross, "CHF")}</td>
					<td class="text-right">${format_currency(e.qst_withheld, "CHF")}</td>
					<td>${e.avs_ok ? '<span class="text-success">✓</span>' : '<span class="text-danger">✗</span>'}</td>
					<td>${cert_badge[e.certificate_status] || ""}
						${
							e.certificate
								? ` <a href="/app/swiss-salary-certificate/${encodeURIComponent(e.certificate)}">${frappe.utils.escape_html(e.certificate)}</a>`
								: ""
						}</td>
					<td class="text-right">${
						e.concordance === null || e.concordance === undefined
							? ""
							: Math.abs(e.concordance) < 1
								? `<span class="text-success">${__("matches")}</span>`
								: `<span class="text-danger">${format_currency(e.concordance, "CHF")}</span>`
					}</td>
				</tr>`,
			)
			.join("");
		parts.push(`
			<div class="frappe-card" style="padding: 15px; margin-bottom: 15px;">
				<h5>${__("Employees")} (${rec.counts.employees}) —
					${rec.counts.certificates_missing} ${__("missing")},
					${rec.counts.certificates_draft} ${__("draft")},
					${rec.counts.certificates_submitted} ${__("validated")},
					${rec.counts.certificates_sent} ${__("sent")}</h5>
				<div style="overflow-x: auto;">
					<table class="table table-sm">
						<thead><tr>
							<th>${__("Employee")}</th><th class="text-center">${__("Slips")}</th>
							<th class="text-right">${__("Gross (year)")}</th>
							<th class="text-right">${__("Source tax withheld")}</th>
							<th>${__("AVS")}</th><th>${__("Certificate")}</th>
							<th class="text-right">${__("Concordance")}</th>
						</tr></thead>
						<tbody>${rows}</tbody>
					</table>
				</div>
			</div>`);

		const qst = this.state.qst;
		if (qst && qst.cantons && qst.cantons.length) {
			const canton_rows = qst.cantons
				.map((c) => {
					const emp_rows = c.employees
						.map(
							(e) => `
							<tr>
								<td style="padding-left: 30px;">${frappe.utils.escape_html(e.employee_name)}</td>
								<td>${frappe.utils.escape_html(e.tariff_code)}</td>
								<td class="text-right">${format_currency(e.gross, "CHF")}</td>
								<td class="text-right">${format_currency(e.withheld, "CHF")}</td>
							</tr>`,
						)
						.join("");
					return `
						<tr style="font-weight: 600; background: var(--bg-light-gray);">
							<td colspan="2">${frappe.utils.escape_html(c.canton)}</td>
							<td class="text-right">${format_currency(c.gross, "CHF")}</td>
							<td class="text-right">${format_currency(c.withheld, "CHF")}</td>
						</tr>${emp_rows}`;
				})
				.join("");
			parts.push(`
				<div class="frappe-card" style="padding: 15px; margin-bottom: 15px;">
					<h5>${__("Source tax by canton (cantonal settlements)")}</h5>
					<div style="overflow-x: auto;">
						<table class="table table-sm">
							<thead><tr>
								<th>${__("Canton / Employee")}</th><th>${__("Tariff")}</th>
								<th class="text-right">${__("Taxable gross")}</th>
								<th class="text-right">${__("Withheld")}</th>
							</tr></thead>
							<tbody>${canton_rows}</tbody>
						</table>
					</div>
				</div>`);
		}

		parts.push(this.render_insurance());
		this.body.html(parts.join(""));
		this.body.find(".btn-record-statement").on("click", (event) => {
			this.record_statement(this.state.insurance.rows[$(event.currentTarget).data("index")]);
		});

		this.page.clear_inner_toolbar();
		if (rec.counts.certificates_missing > 0) {
			this.page.add_inner_button(
				__("Generate {0} certificate(s)", [rec.counts.certificates_missing]),
				() => this.run_generate(),
			);
		}
		if (rec.counts.certificates_draft > 0) {
			this.page.add_inner_button(
				__("Validate {0} certificate(s)", [rec.counts.certificates_draft]),
				() => this.run_submit(),
			);
		}
		if (rec.counts.certificates_submitted > 0) {
			this.page.add_inner_button(
				__("Send {0} certificate(s) to the employees", [
					rec.counts.certificates_submitted,
				]),
				() => this.run_send(rec.counts.certificates_submitted),
			);
		}
		//// Neoffice — the insurers' statements, the reconciliation of their accounts and the
		//// year-end accruals.
		if (this.state.insurance) {
			this.page.add_inner_button(
				__("New Insurer Statement"),
				() => frappe.new_doc("Swiss Insurer Statement", { company: this.args().company }),
				__("Accounting"),
			);
			this.page.add_inner_button(
				__("Reconciliation Report"),
				() =>
					frappe.set_route(
						"query-report",
						"Swiss Social Insurance Reconciliation",
						this.args(),
					),
				__("Accounting"),
			);
			this.page.add_inner_button(
				__("Year-End Accruals"),
				() => this.record_accruals(),
				__("Accounting"),
			);
		}
		const exports = [
			["qst", __("Source tax list (CSV)")],
			["avs", __("AVS recap (CSV)")],
			["laa", __("LAA recap (CSV)")],
		];
		exports.forEach(([kind, label]) => {
			this.page.add_inner_button(
				label,
				() => {
					const args = this.args();
					window.open(
						"/api/method/hrms.regional.switzerland.year_end.export_year_end_csv" +
							`?company=${encodeURIComponent(args.company)}` +
							`&fiscal_year=${encodeURIComponent(args.fiscal_year)}&kind=${kind}`,
					);
				},
				__("Exports"),
			);
		});
	}
}

//// Neoffice — the canton of a source tax final statement, when several are still open: what the
//// slips withheld there, what its statements already recorded, and what remains.
function pick_canton(cantons) {
	return new Promise((resolve) => {
		const rows = cantons
			.map(
				(c) => `<tr>
					<td>${frappe.utils.escape_html(c.canton)}</td>
					<td class="text-right">${format_currency(c.withheld, "CHF")}</td>
					<td class="text-right">${format_currency(c.recorded, "CHF")}</td>
					<td class="text-right"><b>${format_currency(c.remaining, "CHF")}</b></td>
					<td class="text-right">${c.rate ? c.rate + " %" : ""}</td>
				</tr>`,
			)
			.join("");
		const dialog = new frappe.ui.Dialog({
			title: __("Source tax: which canton?"),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "cantons",
					options: `<p class="text-muted small">${__(
						"One final statement per canton: each canton invoices its own source tax and leaves its own collection commission.",
					)}</p>
					<table class="table table-sm">
						<thead><tr>
							<th>${__("Canton")}</th>
							<th class="text-right">${__("Withheld")}</th>
							<th class="text-right">${__("Already recorded")}</th>
							<th class="text-right">${__("Remaining")}</th>
							<th class="text-right">${__("Commission")}</th>
						</tr></thead>
						<tbody>${rows}</tbody>
					</table>`,
				},
				{
					fieldtype: "Select",
					fieldname: "canton",
					label: __("Canton"),
					reqd: 1,
					options: cantons.map((c) => c.canton),
					default: cantons[0].canton,
				},
			],
			primary_action_label: __("Record the final statement"),
			primary_action: ({ canton }) => {
				resolve(cantons.find((c) => c.canton === canton));
				dialog.hide();
			},
		});
		// Closed without choosing: nothing to record (a resolved promise ignores the second call).
		dialog.onhide = () => resolve(null);
		dialog.show();
	});
}
