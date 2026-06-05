// Scope the Account pickers in both child grids to non-group leaves in the
// chosen sanstha company (Bank rows additionally to account_type = "Bank").
frappe.ui.form.on("CyberVidya Other Fees Mapping", {
	setup(frm) {
		frm.set_query("income_account", "fee_heads", () => {
			return { filters: { company: frm.doc.sanstha_company || "", is_group: 0 } };
		});
		frm.set_query("ledger_account", "channels", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			const filters = { company: frm.doc.sanstha_company || "", is_group: 0 };
			if (row && row.channel_type === "Bank") {
				filters.account_type = "Bank";
			}
			return { filters };
		});
	},
	sanstha_company(frm) {
		// Clear now-mismatched account links when the sanstha changes.
		(frm.doc.fee_heads || []).forEach((row) => {
			if (row.income_account) {
				frappe.model.set_value(row.doctype, row.name, "income_account", null);
			}
		});
		(frm.doc.channels || []).forEach((row) => {
			if (row.ledger_account) {
				frappe.model.set_value(row.doctype, row.name, "ledger_account", null);
			}
		});
	},
});
