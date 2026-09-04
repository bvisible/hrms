//// Neoffice — added file (no upstream equivalent): desk page driving the monthly Swiss payroll
//// cycle (preflight, generate, summary, submit).
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.pages["swiss-payroll-cycle"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Swiss Payroll Cycle"),
		single_column: true,
	});
	wrapper.cycle = new SwissPayrollCycle(page);
};

class SwissPayrollCycle {
	constructor(page) {
		this.page = page;
		this.state = {};
		this.make_filters();
		this.body = $('<div class="swiss-cycle-body" style="padding: 15px 0;"></div>').appendTo(
			this.page.main
		);
		this.render_empty();
	}

	make_filters() {
		const today = frappe.datetime.get_today().split("-");
		this.company_field = this.page.add_field({
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		});
		this.month_field = this.page.add_field({
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Select",
			options: [
				{ value: "1", label: __("January") },
				{ value: "2", label: __("February") },
				{ value: "3", label: __("March") },
				{ value: "4", label: __("April") },
				{ value: "5", label: __("May") },
				{ value: "6", label: __("June") },
				{ value: "7", label: __("July") },
				{ value: "8", label: __("August") },
				{ value: "9", label: __("September") },
				{ value: "10", label: __("October") },
				{ value: "11", label: __("November") },
				{ value: "12", label: __("December") },
			],
			default: String(parseInt(today[1], 10)),
		});
		this.year_field = this.page.add_field({
			fieldname: "year",
			label: __("Year"),
			fieldtype: "Int",
			default: parseInt(today[0], 10),
		});
		this.page.set_primary_action(__("Analyse"), () => this.run_preflight(), "search");
	}

	args() {
		return {
			company: this.company_field.get_value(),
			year: this.year_field.get_value(),
			month: this.month_field.get_value(),
		};
	}

	render_empty() {
		this.body.html(
			`<div class="text-muted" style="padding: 40px; text-align: center;">
				${__("Pick a company and a period, then run the analysis.")}
			</div>`
		);
	}

	async call(method, extra_args = {}) {
		const r = await frappe.call({
			method: `hrms.regional.switzerland.monthly_cycle.${method}`,
			args: { ...this.args(), ...extra_args },
			freeze: true,
			freeze_message: __("Working..."),
		});
		return r.message;
	}

	async run_preflight() {
		if (!this.company_field.get_value()) {
			frappe.msgprint(__("Please select a company"));
			return;
		}
		this.state.preflight = await this.call("preflight");
		this.state.summary = await this.call("summary");
		this.render();
	}

	async run_generate() {
		const res = await this.call("generate");
		let message = __("{0} slip(s) created, {1} skipped", [
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
		frappe.msgprint({ title: __("Cycle generation"), message: message, indicator: res.failed.length ? "orange" : "green" });
		await this.run_preflight();
	}

	run_submit() {
		const drafts = this.state.summary?.totals?.draft || 0;
		frappe.confirm(
			__("Submit {0} draft salary slip(s) for this period? This finalizes the payroll.", [
				drafts,
			]),
			async () => {
				const res = await this.call("submit_cycle");
				let message = __("{0} slip(s) submitted", [res.submitted.length]);
				if (res.failed.length) {
					message += "<br><b>" + __("{0} failed", [res.failed.length]) + "</b>";
					res.failed.forEach((f) => {
						//// Neoffice — f.error escaped too, see run_generate above: it is a raw
						//// server traceback line going into an HTML msgprint.
						message += `<br>${frappe.utils.escape_html(f.slip)}: ${frappe.utils.escape_html(f.error)}`;
					});
				}
				frappe.msgprint({
					title: __("Cycle submission"),
					message: message,
					indicator: res.failed.length ? "orange" : "green",
				});
				await this.run_preflight();
			}
		);
	}

	render() {
		const pf = this.state.preflight;
		const sum = this.state.summary;
		const parts = [];

		// --- Issues ---
		if (pf.issues.length) {
			const rows = pf.issues
				.map(
					(i) => `
					<div class="indicator-pill ${i.level === "error" ? "red" : "orange"}" style="margin: 2px 6px 2px 0;">
						${frappe.utils.escape_html(i.message)}
					</div>`
				)
				.join("");
			parts.push(`
				<div class="frappe-card" style="padding: 15px; margin-bottom: 15px;">
					<h5>${__("Checks")} — ${
						pf.ok
							? `<span class="text-success">${__("ready")}</span>`
							: `<span class="text-danger">${__("issues found")}</span>`
					}</h5>
					<div style="display: flex; flex-wrap: wrap;">${rows}</div>
				</div>`);
		} else {
			parts.push(`
				<div class="frappe-card" style="padding: 15px; margin-bottom: 15px;">
					<h5 class="text-success">${__("All checks passed")}</h5>
				</div>`);
		}

		// --- Employees ---
		const status_badge = {
			to_generate: `<span class="indicator-pill blue">${__("to generate")}</span>`,
			draft: `<span class="indicator-pill orange">${__("draft")}</span>`,
			submitted: `<span class="indicator-pill green">${__("submitted")}</span>`,
		};
		const emp_rows = pf.employees
			.map(
				(e) => `
				<tr>
					<td>${frappe.utils.escape_html(e.employee_name)}</td>
					<td>${status_badge[e.status] || e.status}</td>
					<td class="text-muted small">${frappe.utils.escape_html((e.notes || []).join(" · "))}</td>
					<td>${
						e.slip
							? `<a href="/app/salary-slip/${encodeURIComponent(e.slip)}">${frappe.utils.escape_html(
									e.slip
								)}</a>`
							: ""
					}</td>
				</tr>`
			)
			.join("");
		parts.push(`
			<div class="frappe-card" style="padding: 15px; margin-bottom: 15px;">
				<h5>${__("Employees")} (${pf.counts.total}) —
					${pf.counts.to_generate} ${__("to generate")},
					${pf.counts.draft} ${__("draft")},
					${pf.counts.submitted} ${__("submitted")}</h5>
				<div style="overflow-x: auto;">
					<table class="table table-sm">
						<thead><tr>
							<th>${__("Employee")}</th><th>${__("Status")}</th>
							<th>${__("Notes")}</th><th>${__("Salary Slip")}</th>
						</tr></thead>
						<tbody>${emp_rows}</tbody>
					</table>
				</div>
			</div>`);

		// --- Summary ---
		if (sum && sum.slips.length) {
			const comp_rows = sum.components
				.map(
					(c) => `
					<tr>
						<td>${c.type === "earnings" ? __("Earning") : __("Deduction")}</td>
						<td>${frappe.utils.escape_html(c.component)}</td>
						<td class="text-right">${format_currency(c.total, "CHF")}</td>
					</tr>`
				)
				.join("");
			parts.push(`
				<div class="frappe-card" style="padding: 15px; margin-bottom: 15px;">
					<h5>${__("Period totals")} — ${__("Gross")} ${format_currency(
						sum.totals.gross,
						"CHF"
					)} · ${__("Net")} ${format_currency(sum.totals.net, "CHF")}</h5>
					<div style="overflow-x: auto;">
						<table class="table table-sm">
							<thead><tr><th>${__("Type")}</th><th>${__("Component")}</th>
								<th class="text-right">${__("Total")}</th></tr></thead>
							<tbody>${comp_rows}</tbody>
						</table>
					</div>
				</div>`);
		}

		this.body.html(parts.join(""));

		// --- Actions ---
		this.page.clear_inner_toolbar();
		if (pf.counts.to_generate > 0) {
			this.page.add_inner_button(
				__("Generate {0} slip(s)", [pf.counts.to_generate]),
				() => this.run_generate()
			);
		}
		if (pf.counts.draft > 0) {
			this.page.add_inner_button(
				__("Submit {0} draft(s)", [pf.counts.draft]),
				() => this.run_submit()
			);
		}
		if (pf.counts.submitted > 0) {
			this.page.add_inner_button(__("Payment file (pain.001)"), () => this.download_payment_file());
		}
	}

	async download_payment_file() {
		const args = this.args();
		// Preflight: show blocking issues before offering the download
		const r = await frappe.call({
			method: "hrms.regional.switzerland.payment_file.get_salary_payments",
			args: args,
			freeze: true,
			freeze_message: __("Working..."),
		});
		const data = r.message;
		const errors = (data.issues || []).filter((i) => i.level === "error");
		if (data.debtor_error) {
			errors.push({ message: data.debtor_error });
		}
		if (errors.length) {
			frappe.msgprint({
				title: __("Payment file"),
				indicator: "red",
				message: errors.map((i) => frappe.utils.escape_html(i.message)).join("<br>"),
			});
			return;
		}
		const warnings = (data.issues || []).filter((i) => i.level === "warning");
		const summary =
			__("{0} payment(s), total {1}", [
				data.payments.length,
				format_currency(data.total, "CHF"),
			]) +
			(warnings.length
				? "<br>" + warnings.map((i) => frappe.utils.escape_html(i.message)).join("<br>")
				: "");

		frappe.prompt(
			[
				{
					fieldname: "info",
					fieldtype: "HTML",
					options: `<div style="margin-bottom: 10px;">${summary}</div>`,
				},
				{
					fieldname: "execution_date",
					fieldtype: "Date",
					label: __("Execution date"),
					default: frappe.datetime.get_today(),
					reqd: 1,
				},
			],
			(values) => {
				window.open(
					"/api/method/hrms.regional.switzerland.payment_file.download_pain001" +
						`?company=${encodeURIComponent(args.company)}` +
						`&year=${encodeURIComponent(args.year)}&month=${encodeURIComponent(args.month)}` +
						`&execution_date=${encodeURIComponent(values.execution_date)}`
				);
			},
			__("Salary payment file (pain.001)"),
			__("Download")
		);
	}
}
