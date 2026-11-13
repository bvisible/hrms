//// Neoffice — added file (no upstream equivalent): the screen of a labour agreement (lot T,
//// neoffice-maintenance#2623). Its lines in words, grouped as the working time groups them, each with its source
//// and its state; a line is confirmed by a person, one at a time or all those read at once; a template is copied
//// in a dialog; the employees tied to the agreement and the journal of the confirmations have their tabs. Nothing
//// here decides a figure: the server writes the values in words (hr/working_time/views.py) and keeps the rules.
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

const LTA = "hrms.hr.working_time";

frappe.ui.form.on("Labour Agreement", {
	setup(frm) {
		lta_style();
	},

	refresh(frm) {
		// the lines are read and confirmed in the screen; the table stays for an agreement started empty
		frm.toggle_display("section_rules", frm.is_new() || !(frm.doc.rules || []).length);
		frm.toggle_display(["template", "template_version", "template_expires_on"], false);
		if (frm.is_new()) {
			frm.fields_dict.screen.$wrapper.html("");
			lta_template_dialog(frm);
			return;
		}
		frm.lta_tab = frm.lta_tab || "lines";
		lta_render(frm);
	},
});

async function lta_render(frm) {
	const view = await frappe.xcall(`${LTA}.views.agreement_view`, { agreement: frm.doc.name });
	frm.lta_view = view;
	const $screen = frm.fields_dict.screen.$wrapper;
	$screen.html(
		`<div class="lta">${lta_head(view)}${lta_tabs(
			frm,
			view,
		)}<div class="lta-body"></div></div>`,
	);
	const $body = $screen.find(".lta-body");
	if (frm.lta_tab === "employees") $body.html(lta_employees(view));
	else if (frm.lta_tab === "journal") $body.html(lta_journal(view));
	else $body.html(lta_lines(view));

	$screen.find("[data-lta-tab]").on("click", (event) => {
		frm.lta_tab = $(event.currentTarget).attr("data-lta-tab");
		lta_render(frm);
	});
	$screen.find("[data-lta-confirm]").on("click", (event) => {
		event.stopPropagation();
		lta_confirm(frm, [$(event.currentTarget).attr("data-lta-confirm")]);
	});
	$screen.find("[data-lta-row]").on("click", (event) => {
		if (view.can_write) lta_edit_line(frm, $(event.currentTarget).attr("data-lta-row"));
	});
	$screen.find("[data-lta-attach]").on("click", () => lta_attach_dialog(frm));

	frm.clear_custom_buttons();
	if (view.can_write) {
		frm.add_custom_button(__("Use a template"), () => lta_template_dialog(null));
		const ready = view.groups.flatMap((group) => group.rows).filter((row) => row.confirmable);
		if (ready.length) {
			frm.add_custom_button(__("Confirm the {0} lines read", [ready.length]), () =>
				frappe.confirm(
					__(
						"Confirm the {0} lines that wait for it? Each one is then stamped with your name and the moment, and the working time reads it.",
						[ready.length],
					),
					() =>
						lta_confirm(
							frm,
							ready.map((row) => row.name),
						),
				),
			).addClass("btn-primary");
		}
	}
}

function lta_head(view) {
	const pill = view.expired
		? lta_pill(
				__("The template expired on {0}", [
					frappe.datetime.str_to_user(view.template_expires_on),
				]),
				"red",
		  )
		: view.to_confirm
		  ? lta_pill(__("{0} lines to confirm", [view.to_confirm]), "amber")
		  : lta_pill(__("Every line read"), "green");
	const facts = [
		view.kind,
		view.template && view.read_on
			? __("from the template of {0}", [frappe.datetime.str_to_user(view.read_on)])
			: "",
		view.template_expires_on && !view.expired
			? __("the template expires on {0}", [
					frappe.datetime.str_to_user(view.template_expires_on),
			  ])
			: "",
		__("{0} employees tied", [view.employees.length]),
	].filter(Boolean);
	return `
		<div class="lta-hero">
			<div class="lta-hero-pill">${pill}</div>
			<div class="lta-hero-main">
				<div class="lta-title">${frappe.utils.escape_html(view.title)}</div>
				<div class="lta-facts">${facts.map(frappe.utils.escape_html).join(" · ")}</div>
			</div>
			<div class="lta-count">
				<div class="lta-big">${view.confirmed} / ${view.total}</div>
				<div class="lta-cap">${__("Lines confirmed")}</div>
			</div>
		</div>
		${
			view.expired
				? `<div class="lta-note">${__(
						"Your confirmed lines go on applying: they are yours. When the new text is out, a new template arrives and shows what changes, line by line.",
				  )}</div>`
				: ""
		}`;
}

function lta_tabs(frm, view) {
	const tab = (key, label) =>
		`<button class="lta-tab ${
			frm.lta_tab === key ? "is-on" : ""
		}" data-lta-tab="${key}">${label}</button>`;
	return `<div class="lta-tabs">
		${tab("lines", __("Lines"))}
		${tab("employees", __("Employees tied ({0})", [view.employees.length]))}
		${tab("journal", __("Journal of the confirmations"))}
	</div>`;
}

function lta_pill(text, tone) {
	return `<span class="lta-pill is-${tone}"><span class="lta-dot"></span><span class="lta-pill-text">${frappe.utils.escape_html(
		text,
	)}</span></span>`;
}

function lta_state(row) {
	if (row.state === "Confirmed") {
		const who = [
			row.confirmed_by,
			row.confirmed_on && frappe.datetime.str_to_user(row.confirmed_on.slice(0, 10)),
		]
			.filter(Boolean)
			.join(" · ");
		return lta_pill(`${row.state_label}${who ? " · " + who : ""}`, "green");
	}
	if (row.state === "Not found") return lta_pill(row.state_label, "grey");
	const tone = row.state === "Deduced" ? "blue" : "amber";
	const button = row.confirmable
		? `<button class="lta-btn" data-lta-confirm="${row.name}">${__("Confirm")}</button>`
		: "";
	return `<span class="lta-state">${lta_pill(row.state_label, tone)}${button}</span>`;
}

function lta_source(row) {
	if (row.state === "Not found") {
		return `<span class="lta-muted">${__("Not found in the text, left empty")}</span>`;
	}
	// the article, the version and the date read; the title of the text is the link's own words
	const article = row.article
		? `<b>${frappe.utils.escape_html(row.article)}</b>`
		: frappe.utils.escape_html(row.source);
	const rest = [
		row.version && __("version {0}", [row.version]),
		row.read_on && __("read on {0}", [frappe.datetime.str_to_user(row.read_on)]),
	]
		.filter(Boolean)
		.map(frappe.utils.escape_html)
		.join(" · ");
	const text = [article, rest].filter(Boolean).join(" · ");
	const title = frappe.utils.escape_html(row.source || "");
	return row.url
		? `<a href="${encodeURI(
				row.url,
		  )}" target="_blank" rel="noopener noreferrer" title="${title}">${text}</a>`
		: `<span title="${title}">${text}</span>`;
}

function lta_lines(view) {
	const head = `<div class="lta-row lta-th">
		<span>${__("Rule")}</span><span>${__("The client's value")}</span><span>${__(
			"Source",
		)}</span><span>${__("State")}</span>
	</div>`;
	const groups = view.groups
		.map(
			(group) => `<div class="lta-group">${frappe.utils.escape_html(group.label)}</div>
		${group.rows
			.map(
				(row) => `<div class="lta-row ${
					view.can_write ? "is-editable" : ""
				}" data-lta-row="${row.name}">
				<span class="lta-rule">${frappe.utils.escape_html(row.label)}</span>
				<span>${row.value ? frappe.utils.escape_html(row.value) : "—"}${
					row.note
						? `<div class="lta-small">${frappe.utils.escape_html(row.note)}</div>`
						: ""
				}</span>
				<span class="lta-src">${lta_source(row)}</span>
				<span>${lta_state(row)}</span>
			</div>`,
			)
			.join("")}`,
		)
		.join("");
	return `<div class="lta-table">${head}${groups}</div>`;
}

function lta_employees(view) {
	const rows = view.employees
		.map(
			(person) => `<a class="lta-row lta-people" href="/app/employee/${encodeURIComponent(
				person.name,
			)}">
			<span class="lta-rule">${frappe.utils.escape_html(person.employee_name || person.name)}</span>
			<span class="lta-muted">${frappe.utils.escape_html(person.name)}</span>
			<span>${frappe.utils.escape_html(__(person.status))}</span>
		</a>`,
		)
		.join("");
	const empty = `<div class="lta-empty">${__(
		"No employee is tied to this agreement: the working time computes nothing for them, their pay and vacation stay as they were.",
	)}</div>`;
	const action = view.can_write
		? `<button class="lta-btn" data-lta-attach="1">${__("Tie employees")}</button>`
		: "";
	return `<div class="lta-table">${rows || empty}</div><div class="lta-actions">${action}</div>`;
}

function lta_journal(view) {
	if (!view.journal.length) {
		return `<div class="lta-empty">${__("No line is confirmed yet.")}</div>`;
	}
	return `<div class="lta-table">${view.journal
		.map(
			(item) => `<div class="lta-row lta-people">
			<span class="lta-rule">${frappe.utils.escape_html(item.label)}</span>
			<span>${frappe.utils.escape_html(item.by || "")}</span>
			<span class="lta-muted">${frappe.datetime.str_to_user(item.on)}</span>
		</div>`,
		)
		.join("")}</div>`;
}

async function lta_confirm(frm, lines) {
	await frappe.xcall(`${LTA}.agreement.confirm_rules`, { agreement: frm.doc.name, lines });
	frappe.show_alert({ message: __("Confirmed"), indicator: "green" });
	await frm.reload_doc();
}

function lta_edit_line(frm, rowname) {
	const row = (frm.doc.rules || []).find((line) => line.name === rowname);
	if (!row) return;
	const dialog = new frappe.ui.Dialog({
		title: __(row.label || row.rule),
		fields: [
			{
				fieldname: "value",
				label: __("The client's value"),
				fieldtype: "Code",
				options: "JSON",
				default: row.value,
				description: __(
					"Written as the working time stores it (a number, a text in quotes, a list of rows). Changing it sets the line back to « to confirm ».",
				),
			},
			{
				fieldname: "source_title",
				label: __("Source"),
				fieldtype: "Data",
				default: row.source_title,
			},
			{
				fieldname: "source_article",
				label: __("Article"),
				fieldtype: "Data",
				default: row.source_article,
			},
			{
				fieldname: "source_version",
				label: __("Version of the Source"),
				fieldtype: "Data",
				default: row.source_version,
			},
			{
				fieldname: "source_url",
				label: __("Link to the Source"),
				fieldtype: "Data",
				options: "URL",
				default: row.source_url,
			},
			{ fieldname: "note", label: __("Note"), fieldtype: "Small Text", default: row.note },
		],
		primary_action_label: __("Save"),
		primary_action: async (values) => {
			Object.assign(row, values);
			await frm.save();
			dialog.hide();
		},
	});
	dialog.show();
}

async function lta_attach_dialog(frm) {
	const view = frm.lta_view;
	const dialog = new frappe.ui.Dialog({
		title: __("Tie employees"),
		fields: [
			{
				fieldname: "who",
				label: __("Who"),
				fieldtype: "Select",
				options: [
					{
						value: "all",
						label: __("The whole team (the active employees of {0})", [
							view.company || __("every company"),
						]),
					},
					{ value: "some", label: __("I choose") },
				],
				default: "all",
			},
			{
				fieldname: "employees",
				label: __("Employees"),
				fieldtype: "MultiSelectList",
				depends_on: "eval:doc.who=='some'",
				get_data: (text) =>
					frappe.db.get_link_options(
						"Employee",
						text,
						view.company ? { company: view.company } : {},
					),
			},
		],
		primary_action_label: __("Tie"),
		primary_action: async (values) => {
			await frappe.xcall(`${LTA}.views.attach_employees`, {
				agreement: frm.doc.name,
				employees: values.who === "some" ? values.employees || [] : null,
				all_active: values.who === "all" ? 1 : 0,
			});
			dialog.hide();
			frm.lta_tab = "employees";
			lta_render(frm);
		},
	});
	dialog.show();
}

async function lta_template_dialog(frm) {
	const templates = await frappe.xcall(`${LTA}.templates.list_templates`);
	let chosen = templates[0] && templates[0].key;
	const card = (item) => {
		const facts = [
			__(item.kind),
			__("read on {0}", [frappe.datetime.str_to_user(item.read_on)]),
			item.expires_on
				? __("the template expires on {0}", [frappe.datetime.str_to_user(item.expires_on)])
				: "",
		].filter(Boolean);
		const counts = __("{0} lines: {1} drawn from the text, {2} deduced, {3} not found", [
			item.lines,
			item.found,
			item.deduced,
			item.not_found,
		]);
		return `<label class="lta-pick ${item.key === chosen ? "is-on" : ""}" data-lta-pick="${
			item.key
		}">
			<input type="radio" name="lta-template" value="${item.key}" ${
				item.key === chosen ? "checked" : ""
			}>
			<span><b>${frappe.utils.escape_html(item.title)}</b>
			<span class="lta-small">${facts.map(frappe.utils.escape_html).join(" · ")}</span>
			<span class="lta-small">${frappe.utils.escape_html(counts)}</span></span>
		</label>`;
	};
	const dialog = new frappe.ui.Dialog({
		title: __("Use a template"),
		size: "large",
		fields: [
			{ fieldname: "intro", fieldtype: "HTML" },
			{
				fieldname: "who",
				label: __("The employees you tie to this agreement"),
				fieldtype: "Select",
				default: "later",
				options: [
					{ value: "all", label: __("The whole team") },
					{ value: "later", label: __("Later") },
				],
			},
		],
		primary_action_label: __("Copy the template"),
		primary_action: async (values) => {
			const name = await frappe.xcall(`${LTA}.templates.create_from_template`, {
				template_key: chosen,
				company: frappe.defaults.get_user_default("Company"),
			});
			if (values.who === "all") {
				await frappe.xcall(`${LTA}.views.attach_employees`, {
					agreement: name,
					all_active: 1,
				});
			}
			dialog.hide();
			frappe.set_route("Form", "Labour Agreement", name);
		},
		secondary_action_label: __("Start from an empty agreement"),
		secondary_action: () => dialog.hide(),
	});
	dialog.fields_dict.intro.$wrapper.html(`<div class="lta">
		<div class="lta-lead">${__(
			"A template fills the lines with their source. Every line arrives « to confirm »: nothing applies before you have read it. What the text does not settle arrives empty.",
		)}</div>
		${templates.map(card).join("")}
	</div>`);
	dialog.fields_dict.intro.$wrapper.on("click", "[data-lta-pick]", (event) => {
		chosen = $(event.currentTarget).attr("data-lta-pick");
		dialog.fields_dict.intro.$wrapper.find("[data-lta-pick]").removeClass("is-on");
		$(event.currentTarget).addClass("is-on");
	});
	dialog.show();
}

function lta_style() {
	if (document.getElementById("lta-style")) return;
	const style = document.createElement("style");
	style.id = "lta-style";
	style.textContent = `
.lta{display:flex;flex-direction:column;gap:16px;color:var(--text-color)}
.lta-hero{position:relative;display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap;border:1px solid rgba(245,93,26,.28);border-radius:18px;padding:26px 24px 20px;background:linear-gradient(115deg,rgba(245,93,26,.10),var(--card-bg) 60%)}
.lta-hero-pill{position:absolute;top:-13px;left:22px;max-width:calc(100% - 44px)}
.lta-hero-main{flex:1;min-width:0}
.lta-title{font-family:Forum,Georgia,serif;font-size:32px;line-height:1.1}
.lta-facts{font-size:14px;color:var(--text-muted);margin-top:6px}
.lta-count{text-align:right}
.lta-big{font-family:Forum,Georgia,serif;font-size:38px;line-height:1}
.lta-cap{font-size:11.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted);margin-top:4px}
.lta-note{font-size:14px;color:var(--text-muted)}
.lta-tabs{display:flex;gap:22px;border-bottom:1px solid var(--border-color);flex-wrap:wrap}
.lta-tab{background:none;border:0;padding:8px 0;font-size:15px;font-weight:600;color:var(--text-muted);border-bottom:2px solid transparent}
.lta-tab.is-on{color:#AA3700;border-bottom-color:#F55D1A}
.lta-table{border:1px solid var(--border-color);border-radius:14px;overflow:hidden;background:var(--card-bg)}
.lta-row{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr) minmax(0,1.4fr) minmax(0,1.2fr);gap:14px;align-items:center;padding:13px 16px;border-top:1px solid var(--border-color);font-size:14px;color:var(--text-color)}
.lta-row.lta-people{grid-template-columns:minmax(0,2fr) minmax(0,1fr) minmax(0,1fr)}
.lta-row.is-editable{cursor:pointer}
.lta-row.is-editable:hover{background:var(--subtle-fg,var(--control-bg))}
.lta-th{border-top:0;font-size:11.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted)}
.lta-group{padding:9px 16px;border-top:1px solid var(--border-color);background:var(--subtle-fg,var(--control-bg));font-size:11.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted)}
.lta-rule{font-weight:600}
.lta-src{color:var(--text-muted)}
.lta-src a{color:inherit;text-decoration:underline;text-decoration-color:var(--border-color)}
.lta-small{display:block;font-size:12.5px;color:var(--text-muted);margin-top:3px}
.lta-muted{color:var(--text-muted)}
.lta-state{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.lta-pill{display:inline-flex;align-items:center;gap:7px;max-width:100%;border-radius:999px;padding:4px 11px;font-size:12.5px;font-weight:500;line-height:1.35}
.lta-pill-text{min-width:0;overflow-wrap:anywhere}
.lta-dot{flex:none;width:6px;height:6px;border-radius:50%;background:currentColor}
.lta-pill.is-green{background:#E6F4EA;color:#15803D}
.lta-pill.is-amber{background:#FDF3DC;color:#A16207}
.lta-pill.is-blue{background:#E8EEFB;color:#1D4ED8}
.lta-pill.is-red{background:#FDEAE4;color:#C2410C}
.lta-pill.is-grey{background:var(--subtle-fg,#ECE7DE);color:var(--text-muted)}
[data-theme=dark] .lta-pill.is-green{background:rgba(21,128,61,.2);color:#86EFAC}
[data-theme=dark] .lta-pill.is-amber{background:rgba(161,98,7,.22);color:#FCD34D}
[data-theme=dark] .lta-pill.is-blue{background:rgba(29,78,216,.22);color:#93C5FD}
[data-theme=dark] .lta-pill.is-red{background:rgba(194,65,12,.22);color:#FDBA74}
[data-theme=dark] .lta-tab.is-on{color:#FF8D64}
.lta-btn{border-radius:10px;padding:7px 14px;font-size:13.5px;font-weight:700;border:0;background:var(--text-color);color:var(--card-bg)}
.lta-actions{display:flex;justify-content:flex-end}
.lta-empty{padding:18px 16px;font-size:14px;color:var(--text-muted)}
.lta-lead{font-size:14.5px;color:var(--text-muted);margin-bottom:6px}
.lta-pick{display:flex;gap:12px;align-items:flex-start;padding:14px 16px;border-radius:12px;border:1px solid var(--border-color);background:var(--card-bg);margin:0 0 10px;font-weight:400;cursor:pointer}
.lta-pick.is-on{border-color:#F55D1A;background:rgba(245,93,26,.06)}
.lta-pick input{margin-top:4px}
@media (max-width:768px){.lta-row{grid-template-columns:1fr}.lta-th{display:none}.lta-hero{flex-direction:column;align-items:flex-start}.lta-count{text-align:left}.lta-title{font-size:26px}}
`;
	document.head.appendChild(style);
}
