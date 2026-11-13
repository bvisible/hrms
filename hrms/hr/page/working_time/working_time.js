//// Neoffice — added file (no upstream equivalent): the weeks and the balances of the working time (lot T,
//// neoffice-maintenance#2623). The team's week (who waits for the employer's approval), a person's week (the days,
//// the clock, the credits, the five figures, the approval) and their balance (the lots and their expiry, or the
//// running balance against its threshold, the legal counter, the rest days and Sundays owed). Every figure is the
//// engine's, read on the server with the reader's rights (hr/working_time/views.py); nothing is typed here.
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const LTW = "hrms.hr.working_time";

frappe.pages["working-time"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Weeks and Balances"),
		single_column: true,
	});
	wrapper.ltw = new WorkingTimeScreen(page);
};

frappe.pages["working-time"].on_page_show = function (wrapper) {
	wrapper.ltw && wrapper.ltw.route();
};

function ltw_hm(hours, signed = false) {
	const value = Number(hours) || 0;
	const minutes = Math.round(Math.abs(value) * 60);
	const text = `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}`;
	if (!signed) return text;
	if (minutes === 0) return text;
	return `${value < 0 ? "−" : "+"} ${text}`;
}

function ltw_esc(text) {
	return frappe.utils.escape_html(text == null ? "" : String(text));
}

function ltw_pill(text, tone) {
	return `<span class="ltw-pill is-${tone}"><span class="ltw-dot"></span><span>${ltw_esc(
		text,
	)}</span></span>`;
}

function ltw_date(value) {
	return value ? frappe.datetime.str_to_user(String(value).slice(0, 10)) : "";
}

class WorkingTimeScreen {
	constructor(page) {
		this.page = page;
		ltw_style();
		this.$body = $(`<div class="ltw"></div>`).appendTo(page.main);
		this.day = frappe.datetime.get_today();
		this.route();
	}

	route() {
		const route = frappe.get_route();
		this.employee = route[1] || null;
		this.tab = route[2] || this.tab || "week";
		if (frappe.route_options && frappe.route_options.day) this.day = frappe.route_options.day;
		frappe.route_options = null;
		return this.employee ? this.show_person() : this.show_team();
	}

	move(weeks) {
		this.day = frappe.datetime.add_days(this.day, 7 * weeks);
		return this.employee ? this.show_person() : this.show_team();
	}

	week_nav(monday) {
		const sunday = frappe.datetime.add_days(monday, 6);
		const number = moment(monday).isoWeek();
		return `<div class="ltw-nav">
			<button class="ltw-arrow" data-ltw-move="-1" aria-label="${__("Previous week")}">‹</button>
			<span>${__("Week {0} · {1} to {2}", [number, ltw_date(monday), ltw_date(sunday)])}</span>
			<button class="ltw-arrow" data-ltw-move="1" aria-label="${__("Next week")}">›</button>
		</div>`;
	}

	bind_nav() {
		this.$body.find("[data-ltw-move]").on("click", (event) => {
			this.move(Number($(event.currentTarget).attr("data-ltw-move")));
		});
	}

	// ---------------------------------------------------------------------------------------- the team

	async show_team() {
		this.page.set_title(__("Weeks and Balances"));
		this.page.clear_primary_action();
		const view = await frappe.xcall(`${LTW}.views.team_view`, { day: this.day });
		const rows = view.employees
			.map((person) => {
				const week = person.week;
				let state = ltw_pill(__("No week kept"), "grey");
				if (week && week.needs_approval && !week.approved_by) {
					state = ltw_pill(__("Hours over waiting for the approval"), "amber");
				} else if (week && week.approved_by) {
					state = ltw_pill(__("Approved · {0}", [week.approved_by]), "green");
				} else if (week) {
					state = ltw_pill(__("Kept", null, "working time"), "green");
				}
				return `<a class="ltw-row ltw-team" href="/app/working-time/${encodeURIComponent(
					person.employee,
				)}">
					<span class="ltw-strong">${ltw_esc(person.employee_name || person.employee)}</span>
					<span>${week ? ltw_hm(week.due) : "—"}</span>
					<span>${week ? ltw_hm(week.done + week.credited) : "—"}</span>
					<span class="${week && week.over ? "ltw-accent" : ""}">${week ? ltw_hm(week.over) : "—"}</span>
					<span>${state}</span>
				</a>`;
			})
			.join("");
		const empty = `<div class="ltw-empty">${__(
			"No active employee is tied to a labour agreement: tie them on the agreement's screen.",
		)}</div>`;
		this.$body.html(`
			<div class="ltw-top">${this.week_nav(view.monday)}</div>
			<div class="ltw-table">
				<div class="ltw-row ltw-team ltw-th"><span>${__(
					"Employee",
					null,
					"working time",
				)}</span><span>${__("Due", null, "working time")}</span><span>${__(
					"Done",
					null,
					"working time",
				)}</span><span>${__("Over", null, "working time")}</span><span>${__(
					"State",
					null,
					"working time",
				)}</span></div>
				${rows || empty}
			</div>`);
		this.bind_nav();
	}

	// ---------------------------------------------------------------------------------------- a person

	async show_person() {
		const tabs = `<div class="ltw-tabs">
			<button class="ltw-tab ${this.tab === "week" ? "is-on" : ""}" data-ltw-tab="week">${__(
				"The week",
				null,
				"working time",
			)}</button>
			<button class="ltw-tab ${this.tab === "balance" ? "is-on" : ""}" data-ltw-tab="balance">${__(
				"The balance",
				null,
				"working time",
			)}</button>
		</div>`;
		const content =
			this.tab === "balance" ? await this.balance_html() : await this.week_html();
		this.$body.html(tabs + content);
		this.$body.find("[data-ltw-tab]").on("click", (event) => {
			this.tab = $(event.currentTarget).attr("data-ltw-tab");
			frappe.set_route("working-time", this.employee, this.tab);
		});
		this.bind_nav();
	}

	async week_html() {
		const view = await frappe.xcall(`${LTW}.views.week_view`, {
			employee: this.employee,
			day: this.day,
		});
		this.page.set_title(view.employee_name || view.employee);
		this.page.clear_primary_action();
		if (!view.agreement) {
			return `<div class="ltw-card"><div class="ltw-title">${ltw_esc(
				view.employee_name,
			)}</div>
				${ltw_pill(__("No agreement", null, "working time"), "grey")}
				<p class="ltw-muted">${__(
					"The working time computes nothing for this person: no week, no balance, no statement. Their pay and vacation stay as they were.",
				)}</p></div>`;
		}
		const f = view.figures;
		if (!f) {
			return `${this.week_nav(view.monday)}<div class="ltw-card">${ltw_pill(
				__("Nothing settles the hours due"),
				"grey",
			)}<p class="ltw-muted">${__(
				"Neither the confirmed lines nor the lines to confirm of the agreement say how many hours are due.",
			)}</p></div>`;
		}
		const kept = view.kept;
		if (view.can_approve) {
			this.page.set_primary_action(__("Approve {0} over", [ltw_hm(kept.over)]), () =>
				frappe.confirm(
					__(
						"Approve the {0} over of this week? Your name and the moment are kept with the approval.",
						[ltw_hm(kept.over)],
					),
					async () => {
						await frappe.xcall(`${LTW}.store.approve_week`, { week: kept.name });
						frappe.show_alert({
							message: __("Approved", null, "working time"),
							indicator: "green",
						});
						this.show_person();
					},
				),
			);
		}
		let pill = "";
		if (view.indicative) pill = ltw_pill(__("Indicative calculation"), "amber");
		else if (kept && kept.needs_approval && !kept.approved_by)
			pill = ltw_pill(__("Hours over waiting for the approval"), "amber");
		else if (kept && kept.approved_by)
			pill = ltw_pill(
				__("Approved by {0} on {1}", [kept.approved_by, ltw_date(kept.approved_on)]),
				"green",
			);
		const facts = [
			ltw_esc(view.employee_name),
			`${Number(view.activity_rate) || 100} %`,
			ltw_esc(view.agreement),
			view.indicative
				? __("indicative: {0} to confirm", [ltw_esc((view.unconfirmed || []).join(", "))])
				: __("every line used is confirmed"),
		].join(" · ");
		const kpi = (value, label, accent) =>
			`<div class="ltw-kpi"><span class="ltw-big ${
				accent ? "ltw-accent" : ""
			}">${value}</span><span class="ltw-cap">${label}</span></div>`;
		const days = view.days
			.map((day) => {
				const date = moment(day.date);
				// the day's name in the reader's language (moment keeps its own, English, locale)
				const name = `${ltw_esc(__(date.format("dddd")).slice(0, 3))}. ${date.format(
					"DD-MM",
				)}`;
				const off = day.kind === "weekly_off" && !day.done;
				const holiday = day.kind === "holiday" && !day.done;
				const credited = day.credited
					? ltw_pill(
							[
								day.leave_type
									? __(day.leave_type)
									: __("Public holiday", null, "working time"),
								ltw_hm(day.credited),
							]
								.filter(Boolean)
								.join(" · "),
							"blue",
					  )
					: "—";
				const difference = day.done + day.credited - day.due;
				const clock = off
					? `<span class="ltw-muted">${__("Day of rest", null, "working time")}</span>`
					: holiday
					  ? `<span class="ltw-muted">${__(
								"Public holiday",
								null,
								"working time",
					    )}</span>`
					  : ltw_esc(day.clock) || "—";
				return `<div class="ltw-row ltw-days">
					<span class="ltw-strong">${name}</span>
					<span>${day.due ? ltw_hm(day.due) : "—"}</span>
					<span>${clock}</span>
					<span>${credited}</span>
					<span>${day.done ? ltw_hm(day.done) : "—"}</span>
					<span class="${difference > 0.75 ? "ltw-accent ltw-strong" : ""}">${
						day.due || day.done ? ltw_hm(difference, true) : "—"
					}</span>
				</div>`;
			})
			.join("");
		const notes = [];
		if (f.needs_approval) {
			notes.push(
				`<div class="ltw-note is-amber"><b>${__(
					"The hours over wait for the employer's approval",
				)}</b> ${ltw_esc(view.approval_article ? `(${view.approval_article})` : "")}. ${__(
					"Approved, they enter the balance; the approval is kept with who and when.",
				)}</div>`,
			);
		}
		if (view.legal_weekly_maximum) {
			notes.push(
				`<div class="ltw-note"><b>${__("The legal base")}</b> : ${__(
					"{0} of {1} at most this week. Nothing is blocked: the employer is warned.",
					[ltw_hm(f.done), ltw_hm(view.legal_weekly_maximum)],
				)}${
					f.legal_excess
						? ` <span class="ltw-accent">${__("{0} above it", [
								ltw_hm(f.legal_excess),
						  ])}</span>`
						: ""
				}</div>`,
			);
		}
		return `
			<div class="ltw-top">${this.week_nav(view.monday)}</div>
			<div class="ltw-hero">
				${pill ? `<div class="ltw-hero-pill">${pill}</div>` : ""}
				<div class="ltw-facts">${facts}</div>
				<div class="ltw-kpis">
					${kpi(ltw_hm(f.due), __("Due", null, "working time"))}
					${kpi(ltw_hm(f.done + f.credited), __("Done · clocked and credited"))}
					${kpi(ltw_hm(f.difference, true), __("Difference", null, "working time"))}
					${kpi(f.tolerance ? ltw_hm(-f.tolerance, true) : ltw_hm(0), __("Tolerance", null, "working time"))}
					${kpi(ltw_hm(f.over, true), __("Hours over", null, "working time"), true)}
				</div>
			</div>
			<div class="ltw-table">
				<div class="ltw-row ltw-days ltw-th"><span>${__("Day", null, "working time")}</span><span>${__(
					"Due",
					null,
					"working time",
				)}</span><span>${__("Clocked", null, "working time")}</span><span>${__(
					"Credited",
					null,
					"working time",
				)}</span><span>${__("Done", null, "working time")}</span><span>${__(
					"Difference",
					null,
					"working time",
				)}</span></div>
				${days}
			</div>
			<div class="ltw-notes">${notes.join("")}</div>`;
	}

	async balance_html() {
		const view = await frappe.xcall(`${LTW}.views.balance_view`, {
			employee: this.employee,
			day: this.day,
		});
		this.page.set_title(view.employee_name || view.employee);
		this.page.clear_primary_action();
		const b = view.balance;
		if (!b) {
			return `<div class="ltw-card">${ltw_pill(__("No way of keeping the balance"), "grey")}
				<p class="ltw-muted">${__(
					"The agreement confirms no line saying how the hours over are kept: there is no balance yet.",
				)}</p></div>`;
		}
		const year = String(view.on_date).slice(0, 4);
		const paid = (b.payable || [])
			.filter((item) => String(item.on).slice(0, 4) === year)
			.reduce((sum, item) => sum + Number(item.hours || 0), 0);
		const next = (b.lots || [])
			.map((lot) => lot.expires)
			.filter(Boolean)
			.sort()[0];
		const rule = [
			ltw_esc(view.kind_label),
			...view.rule_words.map((item) => `${ltw_esc(item.label)} : ${ltw_esc(item.value)}`),
			ltw_esc(view.kind_article),
		]
			.filter(Boolean)
			.join(" · ");
		const kpi = (value, label, accent) =>
			`<div class="ltw-kpi"><span class="ltw-big ${
				accent ? "ltw-accent" : ""
			}">${value}</span><span class="ltw-cap">${label}</span></div>`;
		const lots = (b.lots || [])
			.map(
				(lot) => `<div class="ltw-row ltw-lots">
				<span>${ltw_date(lot.earned)}</span>
				<span>${ltw_hm(lot.hours)}</span>
				<span>${ltw_hm(lot.hours - lot.left)}</span>
				<span class="ltw-strong">${ltw_hm(lot.left)}</span>
				<span>${ltw_date(lot.expires) || "—"}</span>
			</div>`,
			)
			.join("");
		const payable = (b.payable || [])
			.map(
				(item) => `<div class="ltw-row ltw-lots">
				<span>${ltw_date(item.on)}</span>
				<span>${ltw_hm(item.hours)}</span>
				<span>${
					item.supplement_percent == null
						? __("supplement not settled")
						: __("with {0} %", [item.supplement_percent])
				}</span>
				<span></span><span></span>
			</div>`,
			)
			.join("");
		const legal = Object.entries(b.legal || {})
			.map(
				([y, hours]) =>
					__("{0}: {1} of legal overtime", [y, ltw_hm(hours)]) +
					(b.legal_cap ? ` / ${ltw_hm(b.legal_cap)}` : ""),
			)
			.join(" · ");
		const rest = view.rest || {};
		const owed = (rest.rest_owed || [])
			.map(
				(lot) =>
					`<li>${__("{0} day(s) owed from the week of {1}", [
						lot.days,
						ltw_date(lot.week),
					])}${lot.by ? " · " + __("by {0}", [ltw_date(lot.by)]) : ""}${
						lot.overdue
							? " " + ltw_pill(__("Overdue", null, "working time"), "red")
							: ""
					}</li>`,
			)
			.join("");
		const sundays = (rest.sundays_owed || [])
			.map(
				(lot) =>
					`<li>${__("Sunday or public holiday of {0} to compensate", [
						ltw_date(lot.date),
					])}${lot.by ? " · " + __("by {0}", [ltw_date(lot.by)]) : ""}${
						lot.overdue
							? " " + ltw_pill(__("Overdue", null, "working time"), "red")
							: ""
					}</li>`,
			)
			.join("");
		return `
			<div class="ltw-hero">
				${
					next
						? `<div class="ltw-hero-pill">${ltw_pill(
								__("The next lot expires on {0}", [ltw_date(next)]),
								"amber",
						  )}</div>`
						: ""
				}
				<div class="ltw-facts">${rule}</div>
				<div class="ltw-kpis">
					${kpi(ltw_hm(b.total, true), __("Balance", null, "working time"), true)}
					${kpi(ltw_hm(paid), __("Paid this year", null, "working time"))}
					${
						b.supplement && b.supplement.percent != null
							? kpi(`${b.supplement.percent} %`, __("Supplement if paid"))
							: ""
					}
				</div>
			</div>
			${
				lots
					? `<div class="ltw-table"><div class="ltw-row ltw-lots ltw-th"><span>${__(
							"Earned",
							null,
							"working time",
					  )}</span><span>${__("Hours", null, "working time")}</span><span>${__(
							"Compensated",
							null,
							"working time",
					  )}</span><span>${__("Left", null, "working time")}</span><span>${__(
							"Expires on",
							null,
							"working time",
					  )}</span></div>${lots}</div>`
					: ""
			}
			${
				payable
					? `<div class="ltw-sub">${__(
							"To pay",
							null,
							"working time",
					  )}</div><div class="ltw-table">${payable}</div>`
					: ""
			}
			<div class="ltw-notes">
				<div class="ltw-note"><b>${__("The legal counter")}</b> : ${
					legal || __("no legal overtime this year")
				}</div>
				${
					owed || sundays
						? `<div class="ltw-note"><b>${__(
								"Rest",
								null,
								"working time",
						  )}</b><ul class="ltw-list">${owed}${sundays}</ul></div>`
						: ""
				}
			</div>`;
	}
}

function ltw_style() {
	if (document.getElementById("ltw-style")) return;
	const style = document.createElement("style");
	style.id = "ltw-style";
	style.textContent = `
.ltw{max-width:1100px;margin:0 auto;padding:12px 0 40px;display:flex;flex-direction:column;gap:16px;color:var(--text-color)}
.ltw-top{display:flex;justify-content:flex-end}
.ltw-nav{display:inline-flex;align-items:center;gap:10px;font-weight:600;font-size:14.5px}
.ltw-arrow{border:1px solid var(--border-color);background:var(--card-bg);border-radius:9px;width:32px;height:32px;font-size:18px;line-height:1;color:var(--text-color)}
.ltw-tabs{display:flex;gap:22px;border-bottom:1px solid var(--border-color)}
.ltw-tab{background:none;border:0;padding:8px 0;font-size:15px;font-weight:600;color:var(--text-muted);border-bottom:2px solid transparent}
.ltw-tab.is-on{color:#AA3700;border-bottom-color:#F55D1A}
.ltw-hero{position:relative;border:1px solid rgba(245,93,26,.28);border-radius:18px;padding:24px 24px 18px;background:linear-gradient(115deg,rgba(245,93,26,.10),var(--card-bg) 60%);display:flex;flex-direction:column;gap:12px;margin-top:8px}
.ltw-hero-pill{position:absolute;top:-13px;left:22px;max-width:calc(100% - 44px)}
.ltw-facts{font-size:14px;color:var(--text-muted)}
.ltw-kpis{display:flex;flex-wrap:wrap;gap:0}
.ltw-kpi{display:flex;flex-direction:column;gap:4px;padding:0 22px;border-left:1px solid rgba(245,93,26,.25)}
.ltw-kpi:first-child{border-left:0;padding-left:0}
.ltw-big{font-family:Forum,Georgia,serif;font-size:34px;line-height:1}
.ltw-cap{font-size:11.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted)}
.ltw-accent{color:#AA3700}
[data-theme=dark] .ltw-accent,[data-theme=dark] .ltw-tab.is-on{color:#FF8D64}
.ltw-table{border:1px solid var(--border-color);border-radius:14px;overflow:hidden;background:var(--card-bg)}
.ltw-row{display:grid;gap:12px;align-items:center;padding:12px 16px;border-top:1px solid var(--border-color);font-size:14px;color:var(--text-color)}
a.ltw-row:hover{background:var(--subtle-fg,var(--control-bg));text-decoration:none}
.ltw-team{grid-template-columns:minmax(0,2fr) repeat(3,minmax(0,.8fr)) minmax(0,1.6fr)}
.ltw-days{grid-template-columns:minmax(0,.9fr) minmax(0,.7fr) minmax(0,2fr) minmax(0,1.3fr) minmax(0,.7fr) minmax(0,.7fr)}
.ltw-lots{grid-template-columns:repeat(5,minmax(0,1fr))}
.ltw-th{border-top:0;background:var(--subtle-fg,var(--control-bg));font-size:11.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted)}
.ltw-strong{font-weight:600}
.ltw-muted{color:var(--text-muted)}
.ltw-sub{font-family:Forum,Georgia,serif;font-size:22px}
.ltw-notes{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
.ltw-note{border:1px solid var(--border-color);border-radius:14px;padding:14px 16px;font-size:14px;line-height:1.5;background:var(--card-bg)}
.ltw-note.is-amber{background:#FDF3DC;border-color:#F3E2B3;color:#7A4B00}
[data-theme=dark] .ltw-note.is-amber{background:rgba(161,98,7,.18);border-color:rgba(161,98,7,.35);color:var(--text-color)}
.ltw-list{margin:6px 0 0;padding-left:18px}
.ltw-card{border:1px solid var(--border-color);border-radius:16px;padding:20px 22px;background:var(--card-bg);display:flex;flex-direction:column;gap:10px;align-items:flex-start}
.ltw-title{font-family:Forum,Georgia,serif;font-size:28px}
.ltw-empty{padding:18px 16px;font-size:14px;color:var(--text-muted)}
.ltw-pill{display:inline-flex;align-items:center;gap:7px;max-width:100%;border-radius:999px;padding:4px 11px;font-size:12.5px;font-weight:500;line-height:1.35;overflow-wrap:anywhere}
.ltw-dot{flex:none;width:6px;height:6px;border-radius:50%;background:currentColor}
.ltw-pill.is-green{background:#E6F4EA;color:#15803D}
.ltw-pill.is-amber{background:#FDF3DC;color:#A16207}
.ltw-pill.is-blue{background:#E8EEFB;color:#1D4ED8}
.ltw-pill.is-red{background:#FDEAE4;color:#C2410C}
.ltw-pill.is-grey{background:var(--subtle-fg,#ECE7DE);color:var(--text-muted)}
[data-theme=dark] .ltw-pill.is-green{background:rgba(21,128,61,.2);color:#86EFAC}
[data-theme=dark] .ltw-pill.is-amber{background:rgba(161,98,7,.22);color:#FCD34D}
[data-theme=dark] .ltw-pill.is-blue{background:rgba(29,78,216,.22);color:#93C5FD}
[data-theme=dark] .ltw-pill.is-red{background:rgba(194,65,12,.22);color:#FDBA74}
@media (max-width:768px){.ltw-row{grid-template-columns:1fr 1fr}.ltw-th{display:none}.ltw-kpi{padding:6px 14px 6px 0;border-left:0}.ltw-top{justify-content:flex-start}}
`;
	document.head.appendChild(style);
}
