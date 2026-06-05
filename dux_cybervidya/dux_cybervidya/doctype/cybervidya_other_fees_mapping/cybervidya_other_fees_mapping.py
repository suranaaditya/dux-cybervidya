import frappe
from frappe import _
from frappe.model.document import Document


class CyberVidyaOtherFeesMapping(Document):
    """Routes a college's 'other fee' collections into its parent TRUST/SANSTHA
    company. Each fee-head row maps a (normalised) full fee label to a shared
    INCOME leaf in the sanstha; each channel row maps a bank/cash Account-Head
    nomenclature to a bank/cash leaf in the sanstha. Every posting (Dr bank/cash,
    Cr fee income) lives in ``sanstha_company`` — never the college company,
    because one ERPNext Journal Entry is single-company.
    """

    def validate(self):
        self._validate_sanstha()
        self._validate_fee_heads()
        self._validate_channels()

    def _validate_sanstha(self):
        if not self.sanstha_company:
            frappe.throw(_("Sanstha Company is required."))
        if not frappe.db.exists("Company", self.sanstha_company):
            frappe.throw(_("Company {0} does not exist.").format(self.sanstha_company))

    def _validate_fee_heads(self):
        from dux_cybervidya.api.utils import clean_jv_code, normalize_fee_label

        seen = set()
        for row in self.fee_heads or []:
            if not row.fee_label:
                frappe.throw(_("Row {0}: Fee Label is required.").format(row.idx))
            if not row.income_account:
                frappe.throw(_("Row {0}: Income Account is required.").format(row.idx))

            # Keep a readable original; store the normalised key for matching.
            if not row.fee_label_display:
                row.fee_label_display = clean_jv_code(row.fee_label)
            row.fee_label = normalize_fee_label(row.fee_label)

            if row.fee_label in seen:
                frappe.throw(
                    _("Row {0}: Duplicate fee label {1} within this mapping.").format(
                        row.idx, frappe.bold(row.fee_label)
                    )
                )
            seen.add(row.fee_label)

            acc = frappe.db.get_value(
                "Account",
                row.income_account,
                ["is_group", "company", "root_type"],
                as_dict=True,
            )
            if not acc:
                frappe.throw(
                    _("Row {0}: Account {1} does not exist.").format(row.idx, row.income_account)
                )
            if acc.is_group:
                frappe.throw(
                    _("Row {0}: Account {1} is a group account; pick a leaf ledger.").format(
                        row.idx, row.income_account
                    )
                )
            if acc.company != self.sanstha_company:
                frappe.throw(
                    _("Row {0}: Account {1} belongs to company {2}, not the sanstha {3}.").format(
                        row.idx, row.income_account, acc.company, self.sanstha_company
                    )
                )
            if acc.root_type != "Income":
                # Soft warning, not a hard error: most other-fee heads are Income,
                # but a few (e.g. Alumni / Caution funds) may legitimately be a
                # Liability. RGI confirms the root_type per head (CLAUDE.md open item).
                frappe.msgprint(
                    _("Row {0}: Account {1} has root_type {2}, expected Income.").format(
                        row.idx, row.income_account, acc.root_type or "—"
                    ),
                    indicator="orange",
                    alert=True,
                )

    def _validate_channels(self):
        from dux_cybervidya.api.utils import clean_jv_code

        seen = set()
        for row in self.channels or []:
            if row.channel_type not in ("Bank", "Cash"):
                frappe.throw(_("Row {0}: Channel Type must be Bank or Cash.").format(row.idx))
            if not row.cybervidya_account_head:
                frappe.throw(_("Row {0}: CyberVidya Account Head is required.").format(row.idx))
            if not row.ledger_account:
                frappe.throw(_("Row {0}: Ledger Account is required.").format(row.idx))

            row.cybervidya_account_head = clean_jv_code(row.cybervidya_account_head)
            key = (row.channel_type, row.cybervidya_account_head)
            if key in seen:
                frappe.throw(
                    _("Row {0}: Duplicate {1} account head {2} within this mapping.").format(
                        row.idx, row.channel_type, frappe.bold(row.cybervidya_account_head)
                    )
                )
            seen.add(key)

            acc = frappe.db.get_value(
                "Account",
                row.ledger_account,
                ["is_group", "company", "account_type"],
                as_dict=True,
            )
            if not acc:
                frappe.throw(
                    _("Row {0}: Account {1} does not exist.").format(row.idx, row.ledger_account)
                )
            if acc.is_group:
                frappe.throw(
                    _("Row {0}: Account {1} is a group account; pick a leaf ledger.").format(
                        row.idx, row.ledger_account
                    )
                )
            if acc.company != self.sanstha_company:
                frappe.throw(
                    _("Row {0}: Account {1} belongs to company {2}, not the sanstha {3}.").format(
                        row.idx, row.ledger_account, acc.company, self.sanstha_company
                    )
                )
            if row.channel_type == "Bank" and acc.account_type != "Bank":
                frappe.throw(
                    _("Row {0}: Bank channel account {1} is not of type 'Bank' (got {2}).").format(
                        row.idx, row.ledger_account, acc.account_type or "—"
                    )
                )
