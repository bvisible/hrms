//// Neoffice — added file (no upstream equivalent): the settings of the careers page
//// (neoffice-maintenance#1294) — whether the page is online, why, and its switch, at the top.

frappe.ui.form.on("Careers Settings", {
	refresh(frm) {
		hrms_careers_settings.render(frm, (frm.doc.__onload || {}).page_state);
	},
});

window.hrms_careers_settings = {
	render(frm, state) {
		const field = frm.get_field("page_status");
		if (!field || !state) return;
		this.style();

		const [label, tone, text] = this.sentence(state);
		const url = state.url || "";
		const link = state.enabled
			? `<a class="hj-state__url" href="${encodeURI(
					url,
			  )}" target="_blank" rel="noopener">${frappe.utils.escape_html(
					url.replace(/^https?:\/\//, ""),
			  )}</a>`
			: "";
		field.$wrapper.html(`
			<div class="hj-state">
				<div class="hj-state__head">
					<span class="hj-pill hj-pill--${tone}"><span class="hj-pill__dot"></span>${label}</span>
					${link}
				</div>
				<p class="hj-state__text">${text}</p>
				<div class="hj-state__actions"></div>
			</div>`);

		if (!state.switchable) return;
		const $actions = field.$wrapper.find(".hj-state__actions");
		const button = $(
			// switching on is the one thing to do on a page switched off: the primary action then
			`<button class="btn btn-sm ${
				state.enabled ? "btn-default hj-state__btn" : "btn-primary"
			}">${state.enabled ? __("Switch the page off") : __("Switch the page on")}</button>`,
		).appendTo($actions);
		button.on("click", () => {
			if (!state.enabled) return this.switch(frm, 1);
			frappe.confirm(
				__(
					"Switch the jobs page off? Visitors get “page not found” on it, and the site's menu loses its entry. The openings stay as they are.",
				),
				() => this.switch(frm, 0),
			);
		});
	},

	sentence(state) {
		// the design system's status tones (Neoffice Design System §6.3); the words name the page, never a
		// bare « Online » or « Hidden » that another app's catalogue would translate its own way
		if (!state.enabled) {
			return [
				__("Page switched off"),
				"muted",
				__(
					"The page is switched off: its address answers “page not found”, and the site's menu has no entry. The website's plugins (Jobs) switch it as well.",
				),
			];
		}
		const published =
			state.published === 1
				? __("{0} published opening", [state.published])
				: __("{0} published openings", [state.published]);
		if (state.open) {
			const spontaneous = state.spontaneous
				? " " + __("Unsolicited applications are accepted.")
				: "";
			return [
				__("Page online"),
				"success",
				__("The page is online: {0}.", [published]) + spontaneous,
			];
		}
		return [
			__("Page hidden"),
			"warn",
			__(
				"The page is switched on but hidden: no opening is published, and unsolicited applications are not accepted. It appears with the first published opening.",
			),
		];
	},

	switch(frm, enabled) {
		frappe
			.call({
				method: "hrms.hr.careers.plugin.set_page_enabled",
				args: { enabled },
				freeze: true,
			})
			.then((r) => {
				if (!r.message) return;
				frm.doc.__onload = Object.assign(frm.doc.__onload || {}, {
					page_state: r.message,
				});
				this.render(frm, r.message);
				frappe.show_alert({
					message: enabled
						? __("The jobs page is switched on.")
						: __("The jobs page is switched off."),
					indicator: enabled ? "green" : "orange",
				});
			});
	},

	style() {
		if (document.getElementById("hj-state-style")) return;
		$(`<style id="hj-state-style">
			.hj-state{display:flex;flex-direction:column;gap:10px;padding:16px 18px;border:1px solid var(--border-color);border-radius:var(--border-radius-lg, 12px);margin-bottom:8px}
			.hj-state__head{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
			.hj-state__url{font-size:13px;color:var(--text-muted);text-decoration:underline;text-underline-offset:3px}
			.hj-state__text{margin:0;max-width:68ch;color:var(--text-color);line-height:1.5}
			.hj-state__actions:empty{display:none}
			.hj-state__btn{border:1px solid var(--border-color)!important;background:transparent!important}
			.hj-pill{display:inline-flex;align-items:center;gap:6px;padding:4px 11px;border-radius:999px;font-size:12.5px;font-weight:500;white-space:nowrap}
			.hj-pill__dot{width:6px;height:6px;border-radius:50%;background:currentColor}
			.hj-pill--success{background:#E6F4EA;color:#15803D}.hj-pill--warn{background:#FDF3DC;color:#A16207}
			.hj-pill--muted{background:var(--sand-100, var(--bg-light-gray));color:var(--t3, var(--text-muted))}
			[data-theme="dark"] .hj-pill--success{background:rgba(21,128,61,.18);color:#86EFAC}
			[data-theme="dark"] .hj-pill--warn{background:rgba(161,98,7,.2);color:#FCD34D}
		</style>`).appendTo(document.head);
	},
};
