import frappe
from frappe import _
from frappe.model.document import Document


class CyberVidyaJVMap(Document):
    """Global mapping: (CyberVidya JV code, company) -> debit leaf account.

    When a JV-type entry arrives for an institution, the entry credits that
    institution's `Student Receivable Cybervidya - {ABBR}` and debits the
    account resolved here from (jv_code, company). One standalone table is the
    single place to manage all JV-code routings; the company column lets a
    shared JV code resolve to the correct per-company ledger (an ERPNext
    Journal Entry is single-company, so the debit account must live in the
    same company as the credited receivable).
    """

    def validate(self):
        self._normalise()
        self._validate_company()
        self._validate_account()
        self._validate_unique()

    def _normalise(self):
        if self.cybervidya_jv_code:
            # Use the same cleaner the resolver applies to incoming codes, so
            # stored values and API payloads match consistently.
            from dux_cybervidya.api.utils import clean_jv_code
            self.cybervidya_jv_code = clean_jv_code(self.cybervidya_jv_code)

    def _validate_company(self):
        if not self.company:
            frappe.throw(_("Company is required."))
        if not frappe.db.exists("Company", self.company):
            frappe.throw(_("Company {0} does not exist.").format(self.company))

    def _validate_account(self):
        if not self.account:
            frappe.throw(_("Debit Account is required."))
        acc = frappe.db.get_value(
            "Account", self.account, ["is_group", "company"], as_dict=True
        )
        if not acc:
            frappe.throw(_("Account {0} does not exist.").format(self.account))
        if acc.is_group:
            frappe.throw(
                _("Account {0} is a group account; pick a non-group leaf ledger.").format(
                    self.account
                )
            )
        if acc.company != self.company:
            frappe.throw(
                _(
                    "Account {0} belongs to company {1}, not {2}. "
                    "The debit account must live in the receiving institution's company "
                    "(a Journal Entry is single-company)."
                ).format(self.account, acc.company, self.company)
            )

    def _validate_unique(self):
        existing = frappe.db.exists(
            "CyberVidya JV Map",
            {
                "cybervidya_jv_code": self.cybervidya_jv_code,
                "company": self.company,
                "name": ["!=", self.name],
            },
        )
        if existing:
            frappe.throw(
                _(
                    "A JV mapping already exists for code {0} in company {1} ({2}). "
                    "Each (JV code, company) pair must be unique."
                ).format(
                    frappe.bold(self.cybervidya_jv_code), self.company, existing
                )
            )
