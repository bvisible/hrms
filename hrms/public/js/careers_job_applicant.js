//// Neoffice — added file (no upstream equivalent): the applicant's form for the careers page
//// (neoffice-maintenance#1294) — Nora's reading as a card at the top: a help to read, never a decision.

frappe.ui.form.on("Job Applicant", {
	refresh(frm) {
		// the list shows these two; the form draws them in the card
		frm.toggle_display(["careers_score", "careers_completeness"], false);
		hrms_careers_applicant.render(frm);

		if (!frm.is_new() && frm.doc.careers_privacy_consent_on) {
			frm.add_custom_button(
				__("Read again"),
				() => hrms_careers_applicant.reread(frm),
				__("Nora"),
			);
		}
		if (!frm.is_new()) {
			const blind = hrms_careers_applicant.is_blind();
			frm.add_custom_button(blind ? __("Show the identity") : __("Blind reading"), () => {
				hrms_careers_applicant.set_blind(!blind);
				frm.refresh();
			});
			hrms_careers_applicant.apply_blind(frm, blind);
		}
	},
});

window.hrms_careers_applicant = {
	is_blind() {
		try {
			return localStorage.getItem("hrms_careers_blind") === "1";
		} catch (e) {
			return false;
		}
	},

	set_blind(on) {
		try {
			localStorage.setItem("hrms_careers_blind", on ? "1" : "0");
		} catch (e) {
			// private mode: the choice lasts this page only
		}
	},

	apply_blind(frm, blind) {
		frm.toggle_display(["applicant_name", "email_id", "phone_number"], !blind);
		if (blind) frm.page.set_title(__("Applicant"));
	},

	reread(frm) {
		frappe
			.call({
				method: "hrms.hr.careers.review.rerun_review",
				args: { job_applicant: frm.doc.name },
			})
			.then(() => {
				frappe.show_alert({
					message: __("Nora reads the application again."),
					indicator: "blue",
				});
				setTimeout(() => frm.reload_doc(), 1500);
			});
	},

	render(frm) {
		const field = frm.get_field("careers_review_html");
		if (!field) return;
		if (frm.is_new() || !frm.doc.careers_review_status) {
			frm.toggle_display("careers_review_section", false);
			return;
		}
		frm.toggle_display("careers_review_section", true);
		frappe
			.call({
				method: "hrms.hr.careers.review.get_review",
				args: { job_applicant: frm.doc.name },
			})
			.then((r) => field.$wrapper.html(this.card(r.message || {})));
	},

	esc(text) {
		return frappe.utils.escape_html(text == null ? "" : String(text));
	},

	verdict_pill(verdict) {
		// the design system's five status tones (Neoffice Design System §6.3)
		const tones = {
			met: [__("Shown in the file"), "success"],
			partial: [__("Partly"), "warn"],
			not_met: [__("Not shown"), "danger"],
			unknown: [__("Not said"), "muted"],
		};
		const [label, tone] = tones[verdict] || tones.unknown;
		return `<span class="hj-pill hj-pill--${tone}"><span class="hj-pill__dot"></span>${label}</span>`;
	},

	ensure_style() {
		if (document.getElementById("hj-desk-style")) return;
		// tokens scoped to the card, values of the Neoffice Design System (tokens/colors.css),
		// as the theme's own pages do (module_home.css): the clay and sand ramps never leak
		const style = document.createElement("style");
		style.id = "hj-desk-style";
		style.textContent = `
		.hj-desk{--clay-50:#FAEFE6;--clay-100:#F3DECC;--clay-400:#D68A59;--clay-500:#C2723F;--sand-50:#F6F3ED;--sand-100:#ECE7DE;--sand-200:#DCD4C7;
			--ink:#141414;--t2:#524B41;--t3:#968C7C;--surface:#FFFFFF;--head:linear-gradient(115deg,#FDF1E4,#FBF6EE 55%,#FAF8F4);
			--f-display:'Forum','Times New Roman',serif;--f-sans:'Karla',system-ui,-apple-system,'Segoe UI',sans-serif;
			font-family:var(--f-sans);color:var(--ink);border:1px solid var(--sand-200);border-radius:18px;background:var(--surface);overflow:hidden}
		[data-theme="dark"] .hj-desk{--sand-50:rgba(255,251,245,.04);--sand-100:rgba(255,251,245,.08);--sand-200:rgba(255,251,245,.14);
			--ink:#FFFDF8;--t2:#BFB5A4;--t3:#968C7C;--surface:var(--card-bg);--head:linear-gradient(115deg,rgba(214,138,89,.16),rgba(214,138,89,.05))}
		.hj-desk__head{background:var(--head);border-bottom:1px solid var(--clay-100);padding:22px 26px;display:flex;flex-wrap:wrap;gap:22px 34px;align-items:flex-end}
		.hj-desk__intro{flex:1 1 260px}
		.hj-desk__eyebrow{display:flex;align-items:center;gap:8px;font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--t3);font-weight:600}
		.hj-desk__eyebrow img{width:22px;height:22px}
		.hj-desk__title{font-family:var(--f-display);font-size:27px;line-height:1.15;margin:6px 0 0}
		.hj-desk__kpis{display:flex;gap:0}
		.hj-kpi{padding:0 22px;border-left:1px solid var(--clay-100)}
		.hj-kpi:first-child{padding-left:0;border-left:0}
		.hj-kpi__value{font-family:var(--f-display);font-size:46px;line-height:1;font-variant-numeric:tabular-nums}
		.hj-kpi__value small{font-size:18px;color:var(--t3);margin-left:2px}
		.hj-kpi__label{font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--t3);margin-top:6px}
		.hj-desk__body{padding:22px 26px 24px}
		.hj-desk__summary{font-size:15px;line-height:1.6;margin:0 0 18px;max-width:72ch}
		.hj-axes{display:grid;gap:8px;margin:0 0 22px;max-width:520px}
		.hj-axis{display:grid;grid-template-columns:9rem 1fr 2.4rem;gap:12px;align-items:center;font-size:13px;color:var(--t2)}
		.hj-axis__track{height:4px;border-radius:4px;background:var(--sand-100);overflow:hidden}
		.hj-axis__fill{display:block;height:100%;background:var(--clay-400);border-radius:4px}
		.hj-axis__num{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink)}
		.hj-h{font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--t3);font-weight:600;margin:20px 0 8px}
		.hj-crit{width:100%;border-collapse:collapse}
		.hj-crit tr,.hj-crit td{background:transparent!important}
		.hj-crit td{padding:10px 8px 10px 0;border-top:1px solid var(--sand-100);vertical-align:top}
		.hj-crit td:first-child{width:9.5rem}
		.hj-crit__name{font-weight:600}
		.hj-crit__req{color:var(--t3);font-weight:400}
		.hj-crit__quote{color:var(--t2);font-style:italic;font-size:13px;margin-top:3px}
		.hj-pill{display:inline-flex;align-items:center;gap:6px;padding:4px 11px;border-radius:999px;font-size:12.5px;font-weight:500;white-space:nowrap}
		.hj-pill__dot{width:6px;height:6px;border-radius:50%;background:currentColor}
		.hj-pill--success{background:#E6F4EA;color:#15803D}.hj-pill--warn{background:#FDF3DC;color:#A16207}
		.hj-pill--danger{background:#FDEAE4;color:#C2410C}.hj-pill--muted{background:var(--sand-100);color:var(--t3)}
		[data-theme="dark"] .hj-pill--success{background:rgba(21,128,61,.18);color:#86EFAC}[data-theme="dark"] .hj-pill--warn{background:rgba(161,98,7,.2);color:#FCD34D}
		[data-theme="dark"] .hj-pill--danger{background:rgba(194,65,12,.2);color:#FDBA74}
		.hj-cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:4px 28px}
		.hj-cols ul{margin:0;padding-left:18px;line-height:1.55}
		.hj-warn{background:#FDF3DC;color:#A16207;border-radius:10px;padding:10px 14px;font-size:13.5px;margin:0 0 14px}
		[data-theme="dark"] .hj-warn{background:rgba(161,98,7,.2);color:#FCD34D}
		.hj-foot{font-size:12.5px;color:var(--t3);margin:20px 0 0}
		.hj-desk--quiet .hj-desk__body{color:var(--t2)}`;
		document.head.appendChild(style);
	},

	card(data) {
		const esc = (t) => this.esc(t);
		this.ensure_style();
		const head = (title) =>
			`<div class="hj-desk__eyebrow"><img src="/assets/nora/images/nora-orb.svg" alt="">${__(
				"Read by Nora",
			)}</div><h3 class="hj-desk__title">${title}</h3>`;
		if (data.status === "Queued" || data.status === "Failed" || !data.review) {
			const message =
				data.status === "Queued"
					? __("Nora is reading the application. Reload in a moment.")
					: __(
							"Nora could not read this application. Read the documents below, or ask Nora to read it again.",
					  );
			return `<div class="hj-desk hj-desk--quiet"><div class="hj-desk__head"><div class="hj-desk__intro">${head(
				__("Job Applicant Review"),
			)}</div></div><div class="hj-desk__body">${esc(message)}</div></div>`;
		}
		const review = data.review;
		const details = review.details || {};
		const axes = Object.entries(review.axes || {})
			.map(([axis, score]) => {
				const value = Math.max(0, Math.min(100, score));
				return `<div class="hj-axis"><span>${esc(__(axis))}</span>
					<span class="hj-axis__track"><span class="hj-axis__fill" style="width:${value}%"></span></span>
					<span class="hj-axis__num">${value}</span></div>`;
			})
			.join("");
		const list = (items) =>
			`<ul>${(items || []).map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`;
		const column = (title, items) =>
			(items || []).length
				? `<div><div class="hj-h">${title}</div>${list(items)}</div>`
				: "";
		const criteria = (details.criteria || [])
			.map(
				(c) => `<tr><td>${this.verdict_pill(c.verdict)}</td><td>
					<div class="hj-crit__name">${esc(c.criterion)}${
						c.importance === "Required"
							? ` <span class="hj-crit__req">· ${__("required")}</span>`
							: ""
					}</div>
					${
						c.evidence
							? `<div class="hj-crit__quote">« ${esc(c.evidence)} »${
									c.source ? ` — ${esc(c.source)}` : ""
							  }</div>`
							: ""
					}
				</td></tr>`,
			)
			.join("");
		const warnings = [];
		if (data.stale)
			warnings.push(
				__("The criteria changed after this reading: ask Nora to read it again."),
			);
		if (!data.criteria_reviewed)
			warnings.push(
				__(
					"The criteria of this opening were proposed by Nora and nobody has checked them yet.",
				),
			);
		const unread = (details.unread || []).length
			? `<p class="hj-foot">${__("Not readable, open it yourself:")} ${(details.unread || [])
					.map(esc)
					.join(", ")}</p>`
			: "";
		const score = review.score == null ? "–" : review.score;
		return `<div class="hj-desk">
			<div class="hj-desk__head">
				<div class="hj-desk__intro">${head(__("Job Applicant Review"))}</div>
				<div class="hj-desk__kpis">
					<div class="hj-kpi"><div class="hj-kpi__value">${score}<small>/100</small></div><div class="hj-kpi__label">${__(
						"Match with the job",
					)}</div></div>
					<div class="hj-kpi"><div class="hj-kpi__value">${
						review.completeness
					}<small>%</small></div><div class="hj-kpi__label">${__(
						"Complete file",
					)}</div></div>
				</div>
			</div>
			<div class="hj-desk__body">
				${warnings.map((w) => `<p class="hj-warn">${esc(w)}</p>`).join("")}
				<p class="hj-desk__summary">${esc(review.summary)}</p>
				${axes ? `<div class="hj-axes">${axes}</div>` : ""}
				${
					criteria
						? `<div class="hj-h">${__(
								"Reading criteria",
						  )}</div><table class="hj-crit">${criteria}</table>`
						: ""
				}
				<div class="hj-cols">
					${column(__("Strengths"), details.strengths)}
					${column(__("To check"), details.to_check)}
					${column(__("Interview questions"), details.interview_questions)}
					${column(__("Missing"), details.missing)}
				</div>
				${unread}
				<p class="hj-foot">${__(
					"Read by Nora on our own servers. A help to read the application: the decision is yours.",
				)}</p>
			</div>
		</div>`;
	},
};
