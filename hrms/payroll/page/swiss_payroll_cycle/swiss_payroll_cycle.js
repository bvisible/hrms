//// Neoffice — added file (no upstream equivalent): desk page driving the monthly Swiss payroll
//// cycle (preflight, generate, summary, submit, book, pay).
//// Neoffice — 2026-09-24: laid out as a three-step assistant ("do the payroll, pay it, hand the
//// payslips out"), one button per step, the analysis running as soon as a period is picked; the
//// technical detail (checks, employees, totals) folded underneath. The payslips reach the employees
//// at the last step, by e-mail, by post (WebStamp) or handed out (distribution.py).
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.pages["swiss-payroll-cycle"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Monthly Payroll"),
		single_column: true,
	});
	wrapper.cycle = new SwissPayrollCycle(page);
};

// Month names in the user's language, from the browser's locale data: the translation catalogues
// merged from every installed app disagree on their case ("janvier" next to "Mars").
function month_options() {
	const format = new Intl.DateTimeFormat(frappe.boot.lang || "en", {
		month: "long",
		timeZone: "UTC",
	});
	return Array.from({ length: 12 }, (_, i) => {
		const name = format.format(new Date(Date.UTC(2000, i, 1)));
		return { value: String(i + 1), label: name.charAt(0).toLocaleUpperCase() + name.slice(1) };
	});
}

const esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
const CHANNELS = ["Email", "By Post", "By Hand"];
// Swiss Post zones (webstamp.py): 3 at home, 1 Europe, 2 the other countries.
const ZONE_LABELS = () => ({
	3: __("Switzerland"),
	1: __("Europe"),
	2: __("Other countries"),
});
const CHANNEL_LABELS = () => ({
	Email: __("E-mail"),
	"By Post": __("By Post"),
	"By Hand": __("By Hand"),
});

class SwissPayrollCycle {
	constructor(page) {
		this.page = page;
		this.state = {};
		this.make_filters();
		this.body = $('<div class="swiss-cycle-body" style="padding: 15px 0;"></div>').appendTo(
			this.page.main,
		);
		this.render_empty();
		if (this.company_field.get_value()) this.load();
	}

	make_filters() {
		const today = frappe.datetime.get_today().split("-");
		const reload = () => this.load();
		this.company_field = this.page.add_field({
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
			change: reload,
		});
		this.month_field = this.page.add_field({
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Select",
			options: month_options(),
			default: String(parseInt(today[1], 10)),
			change: reload,
		});
		this.year_field = this.page.add_field({
			fieldname: "year",
			label: __("Year"),
			fieldtype: "Int",
			default: parseInt(today[0], 10),
			change: reload,
		});
		this.page.set_secondary_action(__("Refresh"), () => this.load(), "refresh");
	}

	args() {
		return {
			company: this.company_field.get_value(),
			year: this.year_field.get_value(),
			month: this.month_field.get_value(),
		};
	}

	period_label() {
		const month = month_options().find(
			(m) => m.value === String(this.month_field.get_value()),
		);
		return `${month ? month.label : ""} ${this.year_field.get_value() || ""}`.trim();
	}

	render_empty() {
		this.body.html(
			`<div class="text-muted" style="padding: 40px; text-align: center;">
				${__("Pick a company and a month: the payroll of the month appears here.")}
			</div>`,
		);
	}

	async call(method, extra_args = {}, module = "monthly_cycle", period = this.args()) {
		const r = await frappe.call({
			method: `hrms.regional.switzerland.${module}.${method}`,
			args: { ...period, ...extra_args },
			freeze: true,
			freeze_message: __("Working..."),
		});
		return r.message;
	}

	async load() {
		const period = this.args();
		if (!period.company || !period.month || !period.year) {
			this.render_empty();
			return;
		}
		// Changing the year then the month starts two loads: each reads its own period, and only the
		// latest is shown — else September's checks were drawn under May's totals.
		const seq = (this.load_seq = (this.load_seq || 0) + 1);
		const preflight = await this.call("preflight", {}, "monthly_cycle", period);
		const summary = await this.call("summary", {}, "monthly_cycle", period);
		const distribution =
			preflight.counts.submitted > 0
				? await this.call("get_distribution", {}, "distribution", period)
				: null;
		if (seq !== this.load_seq) return;
		this.state = { preflight, summary, distribution };
		this.render();
	}

	// ---------------------------------------------------------------- steps

	steps() {
		const pf = this.state.preflight;
		const t = (this.state.summary && this.state.summary.totals) || {};
		const rows = (this.state.distribution && this.state.distribution.rows) || [];
		const to_do = pf.counts.to_generate + pf.counts.draft;
		const slips_done = pf.counts.submitted > 0 && to_do === 0;
		// Outside the payroll (no salary structure): said, but never holding the step open.
		const no_structure = pf.counts.no_structure
			? " · " +
			  __("{0} without a salary structure: no slip (see the details)", [
					pf.counts.no_structure,
			  ])
			: "";
		const booked_all =
			t.submitted > 0 && (t.booked || 0) + (t.booked_by_payroll_entry || 0) >= t.submitted;
		const proposed =
			(this.state.summary.proposals || []).length > 0 || (t.paid || 0) >= t.submitted;
		const paid_done = booked_all && (proposed || !this.state.summary.payment_proposals);
		// Delivered: e-mailed, or printed from here (by hand, or by post with its stamp).
		const delivered = rows.filter((r) => r.emailed || r.printed_on).length;
		return [
			{
				key: "slips",
				title: __("Salary slips"),
				done: slips_done,
				status:
					(slips_done
						? __("{0} salary slip(s) submitted", [pf.counts.submitted])
						: __("{0} to generate, {1} draft(s), {2} submitted", [
								pf.counts.to_generate,
								pf.counts.draft,
								pf.counts.submitted,
						  ])) + no_structure,
				action:
					to_do > 0
						? { label: __("Do the payroll"), run: () => this.make_slips() }
						: null,
				// Leavers with vacation days left: paid with the exit slip, so before it is submitted.
				extra_action: pf.counts.vacation_balances
					? {
							label: __("Pay the vacation balances ({0})", [
								pf.counts.vacation_balances,
							]),
							run: () => this.pay_vacation_balances(),
					  }
					: null,
			},
			{
				key: "pay",
				title: __("Payment"),
				done: paid_done,
				status: t.submitted
					? __("Booked {0}/{1} · paid {2}/{1}", [
							t.booked || 0,
							t.submitted,
							t.paid || 0,
					  ]) +
					  ((this.state.summary.proposals || []).length
							? " · " +
							  __("Payment proposal") +
							  " " +
							  this.state.summary.proposals
									.map(
										(n) =>
											`<a href="/app/payment-proposal/${encodeURIComponent(
												n,
											)}">${esc(n)}</a>`,
									)
									.join(", ")
							: "")
					: __("After the salary slips."),
				action:
					slips_done && !paid_done
						? { label: __("Pay the salaries"), run: () => this.pay_salaries() }
						: slips_done && !this.state.summary.payment_proposals
						  ? {
									label: __("Payment file (pain.001)"),
									run: () => this.download_payment_file(),
						    }
						  : null,
			},
			{
				key: "send",
				title: __("Payslips to the employees"),
				done: rows.length > 0 && delivered === rows.length,
				status: rows.length
					? __("{0} of {1} sent or printed", [delivered, rows.length])
					: __("After the salary slips."),
				action: null,
			},
		];
	}

	render() {
		const steps = this.steps();
		const current = steps.findIndex((s) => !s.done);
		const cards = steps
			.map((step, i) => {
				const state = step.done ? "done" : i === current ? "current" : "pending";
				const badge =
					state === "done"
						? `<span class="indicator-pill green" style="min-width: 28px; justify-content: center;">✓</span>`
						: `<span class="indicator-pill ${
								state === "current" ? "blue" : "gray"
						  }" style="min-width: 28px; justify-content: center;">${i + 1}</span>`;
				const extra = step.extra_action
					? `<button class="btn btn-default btn-sm spc-extra" data-step="${
							step.key
					  }">${esc(step.extra_action.label)}</button>`
					: "";
				const button = step.action
					? `<button class="btn ${
							state === "current" ? "btn-primary" : "btn-default"
					  } btn-sm spc-action" data-step="${step.key}">${esc(
							step.action.label,
					  )}</button>`
					: "";
				return `
					<div class="frappe-card spc-step" style="padding: 14px 16px; margin-bottom: 10px; display: flex; align-items: center; gap: 14px; ${
						state === "pending" ? "opacity: 0.7;" : ""
					}">
						${badge}
						<div style="flex: 1; min-width: 0;">
							<div style="font-weight: 600;">${esc(step.title)}</div>
							<div class="text-muted small">${step.status}</div>
						</div>
						${extra}${button}
					</div>`;
			})
			.join("");

		this.body.html(`
			<h4 style="margin: 0 0 12px;">${esc(__("Payroll of {0}", [this.period_label()]))}</h4>
			<div class="spc-steps">${cards}</div>
			<div class="spc-distribution"></div>
			<details style="margin-top: 16px;">
				<summary class="text-muted" style="cursor: pointer;">${__(
					"Details: checks, employees, totals",
				)}</summary>
				<div class="spc-details" style="margin-top: 10px;"></div>
			</details>`);

		this.body.find(".spc-action").on("click", (e) => {
			const step = steps.find((s) => s.key === $(e.currentTarget).attr("data-step"));
			if (step && step.action) step.action.run();
		});
		this.body.find(".spc-extra").on("click", (e) => {
			const step = steps.find((s) => s.key === $(e.currentTarget).attr("data-step"));
			if (step && step.extra_action) step.extra_action.run();
		});
		this.render_distribution();
		this.render_details(this.body.find(".spc-details"));
	}

	// ---------------------------------------------------------------- step 1

	make_slips() {
		const pf = this.state.preflight;
		// An employee without a salary structure is outside the payroll, not a blocked slip.
		const errors = (pf.issues || []).filter(
			(i) => i.level === "error" && i.code !== "no_structure",
		);
		const warn = errors.length
			? `<br><br><span class="text-warning">${__(
					"{0} blocking check(s): those employees get no slip until fixed (see the details).",
					[errors.length],
			  )}</span>`
			: "";
		frappe.confirm(
			__(
				"Generate and submit the salary slips of {0} for {1} employee(s)? Submitted slips are final: a correction is a cancellation and an amendment.",
				[this.period_label(), pf.counts.to_generate + pf.counts.draft],
			) + warn,
			async () => {
				const messages = [];
				let failed = [];
				if (pf.counts.to_generate > 0) {
					const gen = await this.call("generate");
					messages.push(__("{0} slip(s) created", [gen.created.length]));
					failed = failed.concat(
						gen.failed.map((f) => `${esc(f.employee)}: ${esc(f.error)}`),
					);
				}
				const sub = await this.call("submit_cycle");
				messages.push(__("{0} slip(s) submitted", [sub.submitted.length]));
				failed = failed.concat(sub.failed.map((f) => `${esc(f.slip)}: ${esc(f.error)}`));
				frappe.msgprint({
					title: __("Salary slips"),
					indicator: failed.length ? "orange" : "green",
					message:
						messages.join(" · ") +
						(failed.length
							? `<br><br><b>${__("{0} failed", [
									failed.length,
							  ])}</b><br>${failed.join("<br>")}`
							: ""),
				});
				await this.load();
			},
		);
	}

	pay_vacation_balances() {
		const issues = (this.state.preflight.issues || []).filter(
			(i) => i.code === "vacation_balance",
		);
		frappe.confirm(
			__("Pay their vacation days left with the exit salary?") +
				"<br><br>" +
				issues.map((i) => esc(i.message)).join("<br>"),
			async () => {
				const res = await this.call("pay_exit_balances", {}, "vacation");
				const lines = res.created.map(
					(c) =>
						`${esc(c.employee_name)}: ${c.days} ${__("day(s)")}, ${format_currency(
							c.amount,
							"CHF",
						)}${
							c.submitted_slip
								? ` — <span class="text-warning">${__(
										"the exit slip {0} is already submitted: cancel and amend it to pay them",
										[esc(c.submitted_slip)],
								  )}</span>`
								: ""
						}`,
				);
				const failed = res.failed.map((f) => `${esc(f.employee_name)}: ${esc(f.error)}`);
				frappe.msgprint({
					title: __("Vacation paid at the exit"),
					indicator: failed.length ? "orange" : "green",
					message: lines.concat(failed).join("<br>") || __("Nothing to pay."),
				});
				await this.load();
			},
		);
	}

	// ---------------------------------------------------------------- step 2

	pay_salaries() {
		const args = this.args();
		const t = this.state.summary.totals;
		// The last day of the PERIOD — frappe.datetime.month_end() only knows the current month.
		const last_day = moment(`${args.year}-${String(args.month).padStart(2, "0")}-01`)
			.endOf("month")
			.format("YYYY-MM-DD");
		const with_proposal = !!this.state.summary.payment_proposals;
		frappe.prompt(
			[
				{
					fieldname: "info",
					fieldtype: "HTML",
					options: `<div class="text-muted small" style="margin-bottom: 8px;">${
						with_proposal
							? __(
									"The salaries are booked in the ledger, then a payment proposal is created: send it to the bank from there (file or EBICS).",
							  )
							: __(
									"The salaries are booked in the ledger, then the payment file is offered.",
							  )
					} ${__("Net to pay: {0}", [format_currency(t.net, "CHF")])}</div>`,
				},
				{
					fieldname: "execution_date",
					fieldtype: "Date",
					label: __("Payment date"),
					default: last_day,
					reqd: 1,
				},
			],
			async (values) => {
				if ((t.booked || 0) + (t.booked_by_payroll_entry || 0) < t.submitted) {
					await this.call("book_salaries");
				}
				if (!with_proposal) {
					await this.load();
					this.download_payment_file(values.execution_date);
					return;
				}
				const res = await this.call("create_salary_payment_proposal", {
					execution_date: values.execution_date,
				});
				if (res.settings_changed) {
					frappe.show_alert({
						message: __("Salary payments enabled in the ERPNextSwiss settings"),
						indicator: "blue",
					});
				}
				frappe.msgprint({
					title: __("Pay the salaries"),
					indicator: "green",
					message: __(
						"Salaries booked and payment proposal {0} created: open it to send the payments to the bank.",
						[
							`<a href="/app/payment-proposal/${encodeURIComponent(
								res.proposal,
							)}">${esc(res.proposal)}</a>`,
						],
					),
				});
				await this.load();
			},
			__("Pay the salaries"),
			__("Book and pay"),
		);
	}

	async download_payment_file(execution_date) {
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
				message: errors.map((i) => esc(i.message)).join("<br>"),
			});
			return;
		}
		const warnings = (data.issues || []).filter((i) => i.level === "warning");
		const summary =
			__("{0} payment(s), total {1}", [
				data.payments.length,
				format_currency(data.total, "CHF"),
			]) +
			(warnings.length ? "<br>" + warnings.map((i) => esc(i.message)).join("<br>") : "");

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
					default: execution_date || frappe.datetime.get_today(),
					reqd: 1,
				},
			],
			(values) => {
				window.open(
					"/api/method/hrms.regional.switzerland.payment_file.download_pain001" +
						`?company=${encodeURIComponent(args.company)}` +
						`&year=${encodeURIComponent(args.year)}&month=${encodeURIComponent(
							args.month,
						)}` +
						`&execution_date=${encodeURIComponent(values.execution_date)}`,
				);
			},
			__("Salary payment file (pain.001)"),
			__("Download"),
		);
	}

	// ---------------------------------------------------------------- step 3

	render_distribution() {
		const target = this.body.find(".spc-distribution");
		const dist = this.state.distribution;
		if (!dist || !dist.rows.length) {
			target.empty();
			return;
		}
		const labels = CHANNEL_LABELS();
		const pill = (color, text) => `<span class="indicator-pill ${color}">${esc(text)}</span>`;
		const status = (r) => {
			if (r.emailed) return pill("green", __("e-mailed"));
			// Context: another app translates a bare "printed" in the masculine ("Imprimé").
			if (r.printed_on) return pill("green", __("printed", null, "payslip status"));
			if (r.channel === "Email")
				return r.email
					? pill("gray", __("to send"))
					: pill("red", __("no e-mail address"));
			if (r.channel === "By Post") {
				if (r.stamp_url) return pill("blue", __("franked, to print"));
				return r.has_address
					? pill("gray", __("to frank"))
					: pill("red", __("no postal address"));
			}
			return pill("gray", __("to print"));
		};
		const rows = dist.rows
			.map(
				(r) => `
				<tr data-slip="${esc(r.slip)}">
					<td><a href="/app/salary-slip/${encodeURIComponent(r.slip)}">${esc(r.employee_name)}</a></td>
					<td class="text-right">${format_currency(r.net_pay, "CHF")}</td>
					<td>
						<select class="form-control input-xs spc-channel" data-employee="${esc(
							r.employee,
						)}" style="max-width: 160px;">
							${CHANNELS.filter((c) => c !== "By Post" || dist.webstamp)
								.map(
									(c) =>
										`<option value="${c}" ${
											c === r.channel ? "selected" : ""
										}>${esc(labels[c])}</option>`,
								)
								.join("")}
						</select>
					</td>
					<td>${status(r)}</td>
				</tr>`,
			)
			.join("");
		const to_email = this.to_email().length;
		const to_stamp = this.to_stamp().length;
		const { pending, printable } = this.to_print();
		target.html(`
			<div class="frappe-card" style="padding: 14px 16px; margin-top: 4px;">
				<div style="display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px;">
					<div style="flex: 1; min-width: 200px; font-weight: 600;">${__(
						"How each payslip reaches its employee",
					)}</div>
					<button class="btn btn-default btn-sm spc-send" ${to_email ? "" : "disabled"}>${__(
						"Send {0} e-mail(s)",
						[to_email],
					)}</button>
					${
						dist.webstamp
							? `<button class="btn btn-default btn-sm spc-stamp" ${
									to_stamp ? "" : "disabled"
							  }>${__("Frank {0} for the post", [to_stamp])}</button>`
							: ""
					}
					<button class="btn btn-default btn-sm spc-print" ${printable.length ? "" : "disabled"}>${
						pending.length || !printable.length
							? __("Print {0}", [pending.length])
							: __("Print {0} again", [printable.length])
					}</button>
				</div>
				<div style="overflow-x: auto;">
					<table class="table table-sm" style="margin: 0;">
						<thead><tr>
							<th>${__("Employee")}</th><th class="text-right">${__("Net")}</th>
							<th>${__("Payslip Delivery")}</th><th>${__("Status")}</th>
						</tr></thead>
						<tbody>${rows}</tbody>
					</table>
				</div>
			</div>`);

		target.find(".spc-channel").on("change", async (e) => {
			const select = $(e.currentTarget);
			await frappe.call({
				method: "hrms.regional.switzerland.distribution.set_channel",
				args: {
					company: this.args().company,
					employee: select.attr("data-employee"),
					channel: select.val(),
				},
			});
			await this.load();
		});
		target.find(".spc-send").on("click", () => this.send_emails());
		target.find(".spc-stamp").on("click", () => this.frank_for_post());
		target.find(".spc-print").on("click", () => this.print_slips());
	}

	// The rows each button acts on: what is left to do for its channel.
	to_email() {
		return this.state.distribution.rows.filter(
			(r) => r.channel === "Email" && r.email && !r.emailed,
		);
	}

	to_stamp() {
		return this.state.distribution.rows.filter(
			(r) => r.channel === "By Post" && r.has_address && !r.stamp_url && !r.printed_on,
		);
	}

	to_print() {
		// Handed out, or posted once franked. Printed already: offered again (a jammed printer).
		const printable = this.state.distribution.rows.filter(
			(r) =>
				!r.emailed &&
				(r.channel === "By Hand" || (r.channel === "By Post" && r.stamp_url)),
		);
		return { pending: printable.filter((r) => !r.printed_on), printable };
	}

	send_emails() {
		const rows = this.to_email();
		frappe.confirm(
			__("Send their payslip by e-mail to {0} employee(s)?", [rows.length]),
			async () => {
				const res = await this.call(
					"send_payslips",
					{ slips: rows.map((r) => r.slip) },
					"distribution",
				);
				frappe.show_alert({
					message: __("{0} e-mail(s) on their way", [res.sent.length]),
					indicator: "green",
				});
				await this.load();
			},
		);
	}

	async frank_for_post() {
		const rows = this.to_stamp();
		if (!rows.length) return;
		// Grouped by Swiss Post zone: a product serves one zone only (an A-mail stamp is refused
		// for an address in Germany), so each group gets its own product.
		const plan = await this.call(
			"get_stamp_plan",
			{ slips: rows.map((r) => r.slip) },
			"distribution",
		);
		const groups = plan.groups.filter((g) => g.products.length);
		const unserved = plan.groups.filter((g) => !g.products.length);
		if (!groups.length) {
			frappe.msgprint(__("No standard letter product in the WebStamp catalogue."));
			return;
		}
		const test = plan.environment !== "Production";
		const zones = ZONE_LABELS();
		const label = (p) => `${p.product_name} — CHF ${format_number(p.price, null, 2)}`;
		const count = groups.reduce((n, g) => n + g.slips.length, 0);
		const recipients = plan.groups
			.map((g) =>
				g.recipients
					.map(
						(r) =>
							`<tr><td>${esc(r.employee_name)}</td><td>${esc(
								[r.address, r.country].filter(Boolean).join(", "),
							)}</td><td class="text-muted">${esc(zones[g.zone])}</td></tr>`,
					)
					.join(""),
			)
			.join("");
		const fields = [
			{
				fieldname: "info",
				fieldtype: "HTML",
				options: `<div class="text-muted small" style="margin-bottom: 8px;">${__(
					"Each payslip gets a WebStamp carrying the postage and the address, printed in the envelope window.",
				)} ${
					test
						? `<b>${__(
								"Test environment: the stamp is a preview marked TEST and nothing is billed.",
						  )}</b>`
						: ""
				}${
					unserved.length
						? `<div class="text-warning" style="margin-top: 6px;">${__(
								"No letter product for {0} in the WebStamp catalogue: {1} payslip(s) left out.",
								[
									unserved.map((g) => esc(zones[g.zone])).join(", "),
									unserved.reduce((n, g) => n + g.slips.length, 0),
								],
						  )}</div>`
						: ""
				}</div>`,
			},
			...groups.map((g) => ({
				fieldname: `zone_${g.zone}`,
				fieldtype: "Select",
				label: `${__("Product")} — ${zones[g.zone]} (${g.slips.length})`,
				reqd: 1,
				options: g.products.map(label).join("\n"),
				default: label(g.products[0]),
			})),
			{
				fieldname: "recipients",
				fieldtype: "HTML",
				options: `<div style="overflow-x: auto; margin-top: 4px;"><table class="table table-sm small" style="margin: 0;"><tbody>${recipients}</tbody></table></div>`,
			},
		];
		frappe.prompt(
			fields,
			(values) => {
				const choice = groups.map((g) => ({
					group: g,
					product: g.products.find((p) => label(p) === values[`zone_${g.zone}`]),
				}));
				if (test) {
					order(choice);
					return;
				}
				const total = choice.reduce(
					(sum, c) => sum + c.product.price * c.group.slips.length,
					0,
				);
				frappe.confirm(
					__("Order {0} stamp(s) for CHF {1}? Swiss Post bills them.", [
						count,
						format_number(total, null, 2),
					]),
					() => order(choice),
				);
			},
			test
				? __("Frank {0} payslip(s) — TEST", [count])
				: __("Frank {0} payslip(s)", [count]),
			__("Frank"),
		);

		const order = async (choice) => {
			let stamped = [];
			let failed = [];
			for (const { group, product } of choice) {
				const res = await this.call(
					"stamp_payslips",
					{
						slips: group.slips,
						product_number: product.product_number,
						product_name: product.product_name,
						product_price: product.price,
					},
					"distribution",
				);
				stamped = stamped.concat(res.stamped);
				failed = failed.concat(res.failed);
			}
			let message = __("{0} payslip(s) franked", [stamped.length]);
			if (failed.length) {
				message +=
					"<br><br><b>" +
					__("{0} failed", [failed.length]) +
					"</b><br>" +
					failed.map((f) => `${esc(f.employee_name)}: ${esc(f.error)}`).join("<br>");
			}
			if (stamped.length) {
				message += "<br><br>" + __("Print them now: the stamp is on each payslip.");
			}
			frappe.msgprint({
				title: __("WebStamp"),
				indicator: failed.length ? (stamped.length ? "orange" : "red") : "green",
				message,
			});
			await this.load();
		};
	}

	async print_slips() {
		const dist = this.state.distribution;
		const { pending, printable } = this.to_print();
		const slips = (pending.length ? pending : printable).map((r) => r.slip);
		if (!slips.length) return;
		// Opened first: a window opened after an asynchronous call is taken for a pop-up and blocked.
		window.open(
			"/api/method/frappe.utils.print_format.download_multi_pdf" +
				"?doctype=" +
				encodeURIComponent("Salary Slip") +
				"&name=" +
				encodeURIComponent(JSON.stringify(slips)) +
				(dist.print_format ? "&format=" + encodeURIComponent(dist.print_format) : "") +
				"&no_letterhead=1",
		);
		await frappe.call({
			method: "hrms.regional.switzerland.distribution.mark_printed",
			args: { ...this.args(), slips },
		});
		await this.load();
	}

	// ---------------------------------------------------------------- details

	render_details(target) {
		const pf = this.state.preflight;
		const sum = this.state.summary;
		const parts = [];

		// --- Issues ---
		if (pf.issues.length) {
			const rows = pf.issues
				.map(
					(i) => `
					<div class="indicator-pill ${
						i.level === "error" ? "red" : "orange"
					}" style="margin: 2px 6px 2px 0;">
						${esc(i.message)}
					</div>`,
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
			no_structure: `<span class="indicator-pill gray">${__("no salary structure")}</span>`,
		};
		const emp_rows = pf.employees
			.map(
				(e) => `
				<tr>
					<td>${esc(e.employee_name)}</td>
					<td>${status_badge[e.status] || esc(e.status)}</td>
					<td class="text-muted small">${esc((e.notes || []).join(" · "))}</td>
					<td>${
						e.slip
							? `<a href="/app/salary-slip/${encodeURIComponent(e.slip)}">${esc(
									e.slip,
							  )}</a>`
							: ""
					}</td>
				</tr>`,
			)
			.join("");
		parts.push(`
			<div class="frappe-card" style="padding: 15px; margin-bottom: 15px;">
				<h5>${__("Employees")} (${pf.counts.total}) —
					${pf.counts.to_generate} ${__("to generate")},
					${pf.counts.draft} ${__("draft")},
					${pf.counts.submitted} ${__("submitted")}${
						pf.counts.no_structure
							? `, ${pf.counts.no_structure} ${__("without a salary structure")}`
							: ""
					}</h5>
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
						<td>${esc(__(c.component))}</td>
						<td class="text-right">${format_currency(c.total, "CHF")}</td>
					</tr>`,
				)
				.join("");
			//// Neoffice — booked by HRMS from a Payroll Entry: say it, the Swiss booking refuses them.
			const link = (doctype, name) =>
				`<a href="/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}">${esc(
					name,
				)}</a>`;
			const t = sum.totals;
			const elsewhere = (sum.payroll_entry_bookings || []).length
				? `<div class="text-warning small" style="margin: -6px 0 10px;">
					${__(
						"{0} slip(s) already booked from a Payroll Entry ({1}): cancel that journal entry to book them through the Swiss payroll, which also books the employer charges.",
						[
							t.booked_by_payroll_entry,
							sum.payroll_entry_bookings
								.map((n) => link("Journal Entry", n))
								.join(", "),
						],
					)}
				</div>`
				: "";
			parts.push(`
				<div class="frappe-card" style="padding: 15px; margin-bottom: 15px;">
					<h5>${__("Period totals")} — ${__("Gross")} ${format_currency(sum.totals.gross, "CHF")} · ${__(
						"Net",
					)} ${format_currency(sum.totals.net, "CHF")}</h5>
					<div class="text-muted small" style="margin: -4px 0 10px;">
						${__("Payroll Booking Method")}: ${esc(__(sum.booking_method || ""))}${
							(sum.accrual_entries || []).length
								? " · " +
								  __("Salaries booked") +
								  ": " +
								  sum.accrual_entries
										.map((n) => link("Journal Entry", n))
										.join(", ")
								: ""
						}
					</div>
					${elsewhere}
					<div style="overflow-x: auto;">
						<table class="table table-sm">
							<thead><tr><th>${__("Type")}</th><th>${__("Component")}</th>
								<th class="text-right">${__("Total")}</th></tr></thead>
							<tbody>${comp_rows}</tbody>
						</table>
					</div>
				</div>`);
		}
		target.html(parts.join(""));
	}
}
