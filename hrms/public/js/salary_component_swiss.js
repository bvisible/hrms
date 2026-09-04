//// Neoffice — added file (no upstream equivalent): Salary Component form script — selecting a
//// Swiss Wage Type fills the ch_subject_to_* insurance-base flags. Wired by the
//// doctype_js entry we added in hooks.py.
// Swiss Wage Type integration for Salary Component
// Auto-populates social insurance base flags when a Swiss Wage Type is selected.

frappe.ui.form.on("Salary Component", {
	ch_wage_type(frm) {
		if (!frm.doc.ch_wage_type) {
			return;
		}
		frappe.db.get_doc("Swiss Wage Type", frm.doc.ch_wage_type).then((wt) => {
			frm.set_value("ch_subject_to_avs", wt.subject_to_avs);
			frm.set_value("ch_subject_to_ac", wt.subject_to_ac);
			frm.set_value("ch_subject_to_laa", wt.subject_to_laa);
			frm.set_value("ch_subject_to_ijm", wt.subject_to_ijm);
			frm.set_value("ch_subject_to_lpp", wt.subject_to_lpp);
			frm.set_value("ch_subject_to_imp", wt.subject_to_imp);
			if (wt.lohnausweis_position) {
				frm.set_value("ch_lohnausweis_position", wt.lohnausweis_position);
			}
			if (wt.type === "Earning" || wt.type === "Deduction") {
				frm.set_value("type", wt.type);
			}
			if (wt.wage_type_name && !frm.doc.description) {
				frm.set_value("description", wt.wage_type_name);
			}
		});
	},
});
