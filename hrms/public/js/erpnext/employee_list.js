//// Neoffice — added file (no upstream equivalent): hiring goes through the wizard (the person, the
//// job, the permit and tax situation, the badge), not the full Employee form — « c'est très
//// compliqué de créer un employé » (2026-09-24). Only where the Swiss payroll runs (the boot says
//// so): the whole fleet is Swiss, and a site without the payroll keeps the form. The form stays one
//// click away anyway: /app/employee/new.
frappe.listview_settings["Employee"] = frappe.listview_settings["Employee"] || {};
(function (settings) {
	const onload = settings.onload;
	settings.onload = function (listview) {
		onload && onload(listview);
		if (!frappe.boot.swiss_payroll) return;
		// The list's own "Add" button and its keyboard shortcut both call make_new_doc.
		listview.make_new_doc = () => frappe.set_route("swiss-employee-wizard");
	};
})(frappe.listview_settings["Employee"]);
