import frappe
from frappe import _
from frappe.model.document import Document


class CyberVidyaAccountMapping(Document):
    def validate(self):
        self._validate_company()
        self._validate_bank_rows()

    def _validate_company(self):
        if not self.company:
            frappe.throw(_("Company is required."))
        if not frappe.db.exists("Company", self.company):
            frappe.throw(_("Company {0} does not exist.").format(self.company))

    def _validate_bank_rows(self):
        seen_bank_codes = set()
        for row in self.bank_accounts or []:
            if not row.cybervidya_bank:
                frappe.throw(_("Row {0}: CyberVidya Bank Code is required.").format(row.idx))
            if not row.bank_account:
                frappe.throw(_("Row {0}: Bank Account is required.").format(row.idx))

            code = row.cybervidya_bank.strip()
            if code in seen_bank_codes:
                frappe.throw(
                    _("Row {0}: Duplicate CyberVidya Bank Code {1} within this mapping.").format(
                        row.idx, frappe.bold(code)
                    )
                )
            seen_bank_codes.add(code)

            account = frappe.db.get_value(
                "Account",
                row.bank_account,
                ["is_group", "account_type", "company"],
                as_dict=True,
            )
            if not account:
                frappe.throw(
                    _("Row {0}: Account {1} does not exist.").format(row.idx, row.bank_account)
                )
            if account.is_group:
                frappe.throw(
                    _("Row {0}: Account {1} is a group account; pick a leaf ledger.").format(
                        row.idx, row.bank_account
                    )
                )
            if account.account_type != "Bank":
                frappe.throw(
                    _("Row {0}: Account {1} is not of type 'Bank' (got {2}).").format(
                        row.idx, row.bank_account, account.account_type or "—"
                    )
                )
            if account.company != self.company:
                frappe.throw(
                    _(
                        "Row {0}: Account {1} belongs to company {2}, not {3}."
                    ).format(row.idx, row.bank_account, account.company, self.company)
                )
