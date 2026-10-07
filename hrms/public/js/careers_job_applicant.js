//// Neoffice — added file (no upstream equivalent): the applicant's form for the careers page
//// (neoffice-maintenance#1294) — Nora's reading as a card at the top: a help to read, never a decision.

frappe.ui.form.on("Job Applicant", {
	refresh(frm) {
		// the list shows these two; the form draws them in the card
		frm.toggle_display(["careers_score", "careers_completeness"], false);
		hrms_careers_applicant.render(frm);

		if (!frm.is_new() && frm.doc.careers_privacy_consent_on) {
			frm.add_custom_button(__("Read again"), () => hrms_careers_applicant.reread(frm), __("Nora"));
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
		frappe.call({ method: "hrms.hr.careers.review.rerun_review", args: { job_applicant: frm.doc.name } }).then(() => {
			frappe.show_alert({ message: __("Nora reads the application again."), indicator: "blue" });
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
			.call({ method: "hrms.hr.careers.review.get_review", args: { job_applicant: frm.doc.name } })
			.then((r) => field.$wrapper.html(this.card(r.message || {})));
	},

	esc(text) {
		return frappe.utils.escape_html(text == null ? "" : String(text));
	},

	verdict_chip(verdict) {
		const labels = {
			met: [__("Shown"), "green"],
			partial: [__("Partly"), "orange"],
			not_met: [__("Not shown"), "red"],
			unknown: [__("Not said"), "gray"],
		};
		const [label, colour] = labels[verdict] || labels.unknown;
		return `<span class="indicator-pill ${colour}">${label}</span>`;
	},

	card(data) {
		const esc = (t) => this.esc(t);
		if (data.status === "Queued") {
			return `<div class="hj-desk-card text-muted">${__("Nora is reading the application. Reload in a moment.")}</div>`;
		}
		if (data.status === "Failed" || !data.review) {
			return `<div class="hj-desk-card text-muted">${__(
				"Nora could not read this application. Read the documents below, or ask Nora to read it again."
			)}</div>`;
		}
		const review = data.review;
		const details = review.details || {};
		const axes = Object.entries(review.axes || {})
			.map(
				([axis, score]) => `<div class="hj-axis"><span>${esc(__(axis))}</span>
				<span class="hj-bar"><span style="width:${Math.max(0, Math.min(100, score))}%"></span></span>
				<span class="hj-num">${score}</span></div>`
			)
			.join("");
		const list = (items) =>
			(items || []).length ? `<ul>${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : "";
		const criteria = (details.criteria || [])
			.map(
				(c) => `<tr><td>${this.verdict_chip(c.verdict)}</td>
				<td><strong>${esc(c.criterion)}</strong>${c.importance === "Required" ? ` <span class="text-muted">· ${__("required")}</span>` : ""}
				${c.evidence ? `<div class="text-muted small">« ${esc(c.evidence)} »${c.source ? ` — ${esc(c.source)}` : ""}</div>` : ""}</td></tr>`
			)
			.join("");
		const notes = [];
		if (data.stale) notes.push(__("The criteria changed after this reading: ask Nora to read it again."));
		if (!data.criteria_reviewed) notes.push(__("The criteria of this opening were proposed by Nora and nobody has checked them yet."));
		const unread = (details.unread || []).length
			? `<p class="text-muted small">${__("Not readable, open it yourself:")} ${(details.unread || []).map(esc).join(", ")}</p>`
			: "";
		return `
		<style>
			.hj-desk-card{border:1px solid var(--border-color);border-radius:var(--border-radius-md);padding:var(--padding-md);background:var(--card-bg)}
			.hj-desk-top{display:flex;gap:2rem;flex-wrap:wrap;align-items:flex-start;margin-bottom:1rem}
			.hj-big{font-size:2.2rem;font-weight:700;line-height:1;font-variant-numeric:tabular-nums}
			.hj-big small{font-size:.9rem;font-weight:400;color:var(--text-muted)}
			.hj-axes{flex:1;min-width:16rem;display:grid;gap:.35rem}
			.hj-axis{display:grid;grid-template-columns:8rem 1fr 2.5rem;gap:.5rem;align-items:center;font-size:.85rem}
			.hj-bar{height:.45rem;background:var(--gray-200);border-radius:1rem;overflow:hidden}
			.hj-bar span{display:block;height:100%;background:var(--primary)}
			.hj-num{text-align:right;font-variant-numeric:tabular-nums}
			.hj-desk-card table{width:100%;margin:.5rem 0 1rem}
			.hj-desk-card td{padding:.4rem .5rem;vertical-align:top;border-top:1px solid var(--border-color)}
			.hj-desk-card td:first-child{width:7.5rem}
			.hj-desk-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(16rem,1fr));gap:1rem}
			.hj-desk-card h5{margin:1rem 0 .4rem;font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted)}
		</style>
		<div class="hj-desk-card">
			${notes.map((n) => `<p class="alert alert-warning small mb-3">${esc(n)}</p>`).join("")}
			<div class="hj-desk-top">
				<div><div class="hj-big">${review.score == null ? "–" : review.score}<small> / 100</small></div>
					<div class="text-muted small">${__("Match with the criteria")}</div></div>
				<div><div class="hj-big">${review.completeness}<small> %</small></div>
					<div class="text-muted small">${__("Complete")}</div></div>
				${axes ? `<div class="hj-axes">${axes}</div>` : ""}
			</div>
			<p>${esc(review.summary)}</p>
			${criteria ? `<h5>${__("Criteria")}</h5><table>${criteria}</table>` : ""}
			<div class="hj-desk-grid">
				${(details.strengths || []).length ? `<div><h5>${__("Strengths")}</h5>${list(details.strengths)}</div>` : ""}
				${(details.to_check || []).length ? `<div><h5>${__("To check")}</h5>${list(details.to_check)}</div>` : ""}
				${(details.interview_questions || []).length ? `<div><h5>${__("Interview questions")}</h5>${list(details.interview_questions)}</div>` : ""}
				${(details.missing || []).length ? `<div><h5>${__("Missing")}</h5>${list(details.missing)}</div>` : ""}
			</div>
			${unread}
			<p class="text-muted small mb-0">${__("Read by Nora on our own servers. A help to read the application: the decision is yours.")}</p>
		</div>`;
	},
};
