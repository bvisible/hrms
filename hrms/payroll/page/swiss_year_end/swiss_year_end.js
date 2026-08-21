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
			</div>`
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
		this.render();
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
				message += `<br>${frappe.utils.escape_html(f.employee)}: ${f.error}`;
			});
		}
		frappe.msgprint({
			title: __("Certificates"),
			message: message,
			indicator: res.failed.length ? "orange" : "green",
		});
		await this.run_reconcile();
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
					</div>`
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
			submitted: `<span class="indicator-pill green">${__("submitted")}</span>`,
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
							: Math.abs(e.concordance) <= 0.05
								? `<span class="text-success">${__("matches")}</span>`
								: `<span class="text-danger">${format_currency(e.concordance, "CHF")}</span>`
					}</td>
				</tr>`
			)
			.join("");
		parts.push(`
			<div class="frappe-card" style="padding: 15px; margin-bottom: 15px;">
				<h5>${__("Employees")} (${rec.counts.employees}) —
					${rec.counts.certificates_missing} ${__("missing")},
					${rec.counts.certificates_draft} ${__("draft")},
					${rec.counts.certificates_submitted} ${__("submitted")}</h5>
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
							</tr>`
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

		this.body.html(parts.join(""));

		this.page.clear_inner_toolbar();
		if (rec.counts.certificates_missing > 0) {
			this.page.add_inner_button(
				__("Generate {0} certificate(s)", [rec.counts.certificates_missing]),
				() => this.run_generate()
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
							`&fiscal_year=${encodeURIComponent(args.fiscal_year)}&kind=${kind}`
					);
				},
				__("Exports")
			);
		});
	}
}
