"""Server-side resolvers, validators, JE builder, and alerting for the
CyberVidya end-of-day fee-collection integration.

All names that touch the chart of accounts are derived from `Company.abbr`
read at request time — never hardcoded. The two ABBR-derived heads use
deliberately different spellings (see CLAUDE.md §3); do not normalise.
"""

import re
from typing import Optional

import frappe
from frappe import _
from frappe.utils import flt, getdate


RECEIVABLE_HEAD_TEMPLATE = "Student Receivable Cybervidya - {abbr}"
PAYABLE_HEAD_TEMPLATE = "Student Payable Cybervidya - {abbr}"
CASH_HEAD_TEMPLATE = "Cash Cyber Vidhya - {abbr}"

# Income GROUP created per sanstha to hold the auto-created other-fee income
# leaves (see api/other_fees.py and scripts/other_fees_import.py).
OTHER_FEES_GROUP_TEMPLATE = "CyberVidya Other Fees - {abbr}"

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Marker we append to custom_cybervidya_ref when a JE is cancelled, so the
# original reference becomes free for CyberVidya to re-post. The cancelled
# JE keeps the suffixed reference (preserves the audit link).
CANCELLED_REF_MARKER = "__CANCELLED__"


class CyberVidyaRejection(Exception):
    """Raised when a payload cannot be turned into a JE. Carries a
    human-readable reason that goes back to the caller verbatim."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------

def validate_payload(raw: dict) -> dict:
    """Coerce + validate the incoming payload. Returns a normalised dict.
    Never trusts caller-supplied types."""
    reference = _require_str(raw, "reference")
    institution = _require_str(raw, "institution")
    collection_type = _require_str(raw, "collection_type").lower()
    if collection_type not in ("bank", "cash"):
        raise CyberVidyaRejection(
            f"collection_type must be 'bank' or 'cash', got {collection_type!r}."
        )

    bank = (raw.get("bank") or "").strip() or None
    if collection_type == "bank" and not bank:
        raise CyberVidyaRejection("bank is required when collection_type is 'bank'.")
    if collection_type == "cash" and bank:
        raise CyberVidyaRejection("bank must be empty when collection_type is 'cash'.")

    amount = flt(raw.get("amount"))
    if amount <= 0:
        raise CyberVidyaRejection(f"amount must be > 0, got {raw.get('amount')!r}.")

    collection_date = _require_str(raw, "collection_date")
    if not ISO_DATE_RE.match(collection_date):
        raise CyberVidyaRejection(
            f"collection_date must be YYYY-MM-DD, got {collection_date!r}."
        )
    try:
        getdate(collection_date)
    except Exception:
        raise CyberVidyaRejection(f"collection_date is not a valid date: {collection_date!r}.")

    return {
        "reference": reference,
        "institution": institution,
        "collection_type": collection_type,
        "bank": bank,
        "amount": amount,
        "collection_date": collection_date,
        "remarks": (raw.get("remarks") or None),
    }


def _require_str(raw: dict, key: str) -> str:
    val = raw.get(key)
    if val is None or (isinstance(val, str) and not val.strip()):
        raise CyberVidyaRejection(f"{key} is required.")
    if not isinstance(val, str):
        raise CyberVidyaRejection(f"{key} must be a string, got {type(val).__name__}.")
    return val.strip()


def validate_jv_payload(raw: dict) -> dict:
    """Validate a JV (journal-voucher / inter-entity) payload. Unlike a
    collection there is no bank/cash channel — instead a `jv_code` resolves
    (with the company) to a debit ledger via CyberVidya JV Map. Returns a
    normalised dict."""
    reference = _require_str(raw, "reference")
    institution = _require_str(raw, "institution")
    jv_code = _require_str(raw, "jv_code")

    amount = flt(raw.get("amount"))
    if amount <= 0:
        raise CyberVidyaRejection(f"amount must be > 0, got {raw.get('amount')!r}.")

    collection_date = _require_str(raw, "collection_date")
    if not ISO_DATE_RE.match(collection_date):
        raise CyberVidyaRejection(
            f"collection_date must be YYYY-MM-DD, got {collection_date!r}."
        )
    try:
        getdate(collection_date)
    except Exception:
        raise CyberVidyaRejection(f"collection_date is not a valid date: {collection_date!r}.")

    return {
        "reference": reference,
        "institution": institution,
        "jv_code": jv_code,
        "amount": amount,
        "collection_date": collection_date,
        "remarks": (raw.get("remarks") or None),
    }


def validate_other_fees_payload(raw: dict) -> dict:
    """Validate an 'other fees' payload. The fee head is credited to an INCOME
    leaf in the college's parent SANSTHA company (resolved server-side), and the
    bank/cash debit ledger also lives in that sanstha. Returns a normalised dict.

    `bank_account_head` (CyberVidya's Account-Head nomenclature) is required for
    a bank record; for cash it is optional (used to disambiguate when an
    institution has more than one cash ledger)."""
    reference = _require_str(raw, "reference")
    institution = _require_str(raw, "institution")
    fee_head = _require_str(raw, "fee_head")
    collection_type = _require_str(raw, "collection_type").lower()
    if collection_type not in ("bank", "cash"):
        raise CyberVidyaRejection(
            f"collection_type must be 'bank' or 'cash', got {collection_type!r}."
        )

    bank_account_head = (raw.get("bank_account_head") or "").strip() or None
    if collection_type == "bank" and not bank_account_head:
        raise CyberVidyaRejection(
            "bank_account_head is required when collection_type is 'bank'."
        )

    amount = flt(raw.get("amount"))
    if amount <= 0:
        raise CyberVidyaRejection(f"amount must be > 0, got {raw.get('amount')!r}.")

    collection_date = _require_str(raw, "collection_date")
    if not ISO_DATE_RE.match(collection_date):
        raise CyberVidyaRejection(
            f"collection_date must be YYYY-MM-DD, got {collection_date!r}."
        )
    try:
        getdate(collection_date)
    except Exception:
        raise CyberVidyaRejection(f"collection_date is not a valid date: {collection_date!r}.")

    return {
        "reference": reference,
        "institution": institution,
        "fee_head": fee_head,
        "collection_type": collection_type,
        "bank_account_head": bank_account_head,
        "amount": amount,
        "collection_date": collection_date,
        "remarks": (raw.get("remarks") or None),
    }


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------

def resolve_company(institution_code: str) -> str:
    mapping_name = frappe.db.get_value(
        "CyberVidya Account Mapping",
        {"cybervidya_institution": institution_code},
        "name",
    )
    if not mapping_name:
        raise CyberVidyaRejection(
            f"No CyberVidya Account Mapping for institution {institution_code!r}."
        )
    company = frappe.db.get_value("CyberVidya Account Mapping", mapping_name, "company")
    if not company:
        raise CyberVidyaRejection(
            f"Mapping for institution {institution_code!r} has no company set."
        )
    return company


def resolve_bank_ledger(institution_code: str, bank_code: str, company: str) -> str:
    rows = frappe.get_all(
        "CyberVidya Bank Map",
        filters={
            "parent": institution_code,
            "parenttype": "CyberVidya Account Mapping",
            "cybervidya_bank": bank_code,
        },
        fields=["bank_account"],
        limit=1,
    )
    if not rows:
        raise CyberVidyaRejection(
            f"No bank mapping for institution {institution_code!r} + bank {bank_code!r}."
        )
    bank_account = rows[0].bank_account
    assert_bank_leaf(bank_account, company)
    return bank_account


def clean_jv_code(s) -> str:
    """Normalise a JV code: NBSP -> space, collapse runs of whitespace, strip.
    The CyberVidya JV Map stores codes in this form and the resolver cleans
    the incoming value the same way, so minor spacing differences still match."""
    return re.sub(r"\s+", " ", str(s or "").replace("\xa0", " ")).strip()


def resolve_jv_account(jv_code: str, company: str) -> str:
    """Resolve a JV code + company to its debit leaf account via the global
    CyberVidya JV Map. Miss -> reject; never fall back to a default account."""
    code = clean_jv_code(jv_code)
    rows = frappe.get_all(
        "CyberVidya JV Map",
        filters={"cybervidya_jv_code": code, "company": company},
        fields=["account"],
        limit=1,
    )
    if not rows:
        raise CyberVidyaRejection(
            f"No JV mapping for code {code!r} in company {company!r}."
        )
    account = rows[0].account
    assert_leaf(account, company)
    return account


def normalize_fee_label(s) -> str:
    """Normalise a fee-head label for matching: NBSP -> space, collapse
    whitespace, strip, lower-case. The CyberVidya Other Fee Head Map stores
    labels in this form and the resolver cleans the incoming label the same
    way, so case / spacing / typo-spacing differences across colleges match."""
    return clean_jv_code(s).lower()


def resolve_sanstha_company(institution_code: str) -> str:
    """Resolve a college CV code to its parent TRUST/SANSTHA company via
    CyberVidya Other Fees Mapping. Other-fee JEs are booked in the sanstha,
    not the college. Miss -> reject."""
    mapping_name = frappe.db.get_value(
        "CyberVidya Other Fees Mapping",
        {"cybervidya_institution": institution_code},
        "name",
    )
    if not mapping_name:
        raise CyberVidyaRejection(
            f"No CyberVidya Other Fees Mapping for institution {institution_code!r}."
        )
    sanstha = frappe.db.get_value(
        "CyberVidya Other Fees Mapping", mapping_name, "sanstha_company"
    )
    if not sanstha:
        raise CyberVidyaRejection(
            f"Other Fees Mapping for institution {institution_code!r} has no sanstha_company set."
        )
    return sanstha


def resolve_fee_account(institution_code: str, fee_label: str, sanstha_company: str) -> str:
    """Resolve (institution, fee label) to the shared INCOME leaf in the sanstha
    via CyberVidya Other Fee Head Map child rows. Match on the normalised label.
    Miss -> reject; never fall back to a default account."""
    key = normalize_fee_label(fee_label)
    rows = frappe.get_all(
        "CyberVidya Other Fee Head Map",
        filters={
            "parent": institution_code,
            "parenttype": "CyberVidya Other Fees Mapping",
            "fee_label": key,
        },
        fields=["income_account"],
        limit=1,
    )
    if not rows:
        raise CyberVidyaRejection(
            f"No fee-head mapping for institution {institution_code!r} + fee {fee_label!r} "
            f"(normalised {key!r})."
        )
    account = rows[0].income_account
    assert_leaf(account, sanstha_company)
    return account


def resolve_other_fees_ledger(
    institution_code: str,
    collection_type: str,
    account_head: Optional[str],
    sanstha_company: str,
) -> str:
    """Resolve the bank/cash DEBIT ledger (in the sanstha) for an other-fees
    record via CyberVidya Other Fees Channel Map child rows.

    bank: match the channel row by normalised Account-Head nomenclature.
    cash: match by Account-Head if supplied; else fall back to the single Cash
          channel row for this institution (reject if absent or ambiguous).
    Miss -> reject.
    """
    channel = "Bank" if collection_type == "bank" else "Cash"
    if account_head:
        head = clean_jv_code(account_head)
        rows = frappe.get_all(
            "CyberVidya Other Fees Channel Map",
            filters={
                "parent": institution_code,
                "parenttype": "CyberVidya Other Fees Mapping",
                "channel_type": channel,
                "cybervidya_account_head": head,
            },
            fields=["ledger_account"],
            limit=1,
        )
        if not rows:
            raise CyberVidyaRejection(
                f"No {channel.lower()} channel mapping for institution "
                f"{institution_code!r} + account head {account_head!r}."
            )
        ledger = rows[0].ledger_account
    else:
        rows = frappe.get_all(
            "CyberVidya Other Fees Channel Map",
            filters={
                "parent": institution_code,
                "parenttype": "CyberVidya Other Fees Mapping",
                "channel_type": channel,
            },
            fields=["ledger_account"],
            limit=2,
        )
        if not rows:
            raise CyberVidyaRejection(
                f"No {channel.lower()} channel mapping for institution {institution_code!r}."
            )
        if len(rows) > 1:
            raise CyberVidyaRejection(
                f"Multiple {channel.lower()} channel mappings for institution "
                f"{institution_code!r}; specify bank_account_head to disambiguate."
            )
        ledger = rows[0].ledger_account

    if collection_type == "bank":
        assert_bank_leaf(ledger, sanstha_company)
    else:
        assert_leaf(ledger, sanstha_company)
    return ledger


def derive_receivable_head(company: str) -> str:
    abbr = _company_abbr(company)
    head = RECEIVABLE_HEAD_TEMPLATE.format(abbr=abbr)
    assert_leaf(head, company)
    return head


def derive_payable_head(company: str) -> str:
    abbr = _company_abbr(company)
    head = PAYABLE_HEAD_TEMPLATE.format(abbr=abbr)
    assert_leaf(head, company)
    return head


def derive_cash_head(company: str) -> str:
    abbr = _company_abbr(company)
    head = CASH_HEAD_TEMPLATE.format(abbr=abbr)
    assert_leaf(head, company)
    return head


def _company_abbr(company: str) -> str:
    abbr = frappe.db.get_value("Company", company, "abbr")
    if not abbr:
        raise CyberVidyaRejection(f"Company {company!r} has no abbr field set.")
    return abbr


# ---------------------------------------------------------------------------
# Account existence / type checks
# ---------------------------------------------------------------------------

def assert_leaf(account_name: str, company: str) -> None:
    acc = frappe.db.get_value(
        "Account",
        account_name,
        ["is_group", "company"],
        as_dict=True,
    )
    if not acc:
        raise CyberVidyaRejection(f"Account {account_name!r} does not exist.")
    if acc.is_group:
        raise CyberVidyaRejection(f"Account {account_name!r} is a group account, not a leaf.")
    if acc.company != company:
        raise CyberVidyaRejection(
            f"Account {account_name!r} belongs to company {acc.company!r}, expected {company!r}."
        )


def assert_bank_leaf(account_name: str, company: str) -> None:
    acc = frappe.db.get_value(
        "Account",
        account_name,
        ["is_group", "company", "account_type"],
        as_dict=True,
    )
    if not acc:
        raise CyberVidyaRejection(f"Bank account {account_name!r} does not exist.")
    if acc.is_group:
        raise CyberVidyaRejection(f"Bank account {account_name!r} is a group account, not a leaf.")
    if acc.company != company:
        raise CyberVidyaRejection(
            f"Bank account {account_name!r} belongs to company {acc.company!r}, expected {company!r}."
        )
    if acc.account_type != "Bank":
        raise CyberVidyaRejection(
            f"Bank account {account_name!r} has account_type {acc.account_type!r}, expected 'Bank'."
        )


# ---------------------------------------------------------------------------
# Journal Entry builder
# ---------------------------------------------------------------------------

def build_and_submit_je(
    *,
    company: str,
    posting_date: str,
    debit_account: str,
    credit_account: str,
    amount: float,
    reference: str,
    remarks: Optional[str] = None,
) -> str:
    """Construct, insert, and submit the Journal Entry. Returns its name."""
    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Journal Entry"
    je.company = company
    je.posting_date = posting_date
    je.user_remark = remarks or f"CyberVidya collection {reference}"
    je.custom_cybervidya_ref = reference

    # P&L (Income/Expense) account lines require a Cost Center in ERPNext.
    # Balance-sheet lines (bank, cash, receivable, payable, due-from) do not.
    # JV write-offs hit an Expense account, so resolve a cost center and attach
    # it only to the P&L line(s). Prefer Company.cost_center; fall back to the
    # company's main non-group cost center.
    default_cc = frappe.get_cached_value("Company", company, "cost_center")
    if not default_cc:
        abbr = frappe.get_cached_value("Company", company, "abbr")
        default_cc = (
            frappe.db.get_value("Cost Center", f"Main - {abbr}", "name")
            or frappe.db.get_value(
                "Cost Center", {"company": company, "is_group": 0}, "name"
            )
        )

    def _line(account, dr, cr):
        row = {
            "account": account,
            "debit_in_account_currency": dr,
            "credit_in_account_currency": cr,
        }
        root = frappe.get_cached_value("Account", account, "root_type")
        if root in ("Income", "Expense"):
            if not default_cc:
                raise CyberVidyaRejection(
                    f"P&L account {account!r} needs a cost center but company "
                    f"{company!r} has no default or non-group cost center."
                )
            row["cost_center"] = default_cc
        return row

    je.append("accounts", _line(debit_account, amount, 0))
    je.append("accounts", _line(credit_account, 0, amount))

    je.insert(ignore_permissions=False)
    je.submit()
    return je.name


# ---------------------------------------------------------------------------
# Cancel hook — free idempotency reference when a CV-posted JE is cancelled
# ---------------------------------------------------------------------------

def on_journal_entry_cancel(doc, method=None):
    """Doc-event hook bound to Journal Entry.on_cancel via hooks.py.

    A cancelled JE has zero ledger impact — it is effectively absent from the
    books. To allow CyberVidya to retry the same logical collection (which
    would otherwise be permanently blocked by the unique constraint on
    custom_cybervidya_ref), we suffix the cancelled JE's reference with
    __CANCELLED__<jename>. This frees the original reference for re-posting
    while preserving an audit link from the cancelled JE.

    No-op on JEs that were not posted by CyberVidya, or whose reference is
    already suffixed.
    """
    ref = doc.get("custom_cybervidya_ref")
    if not ref or CANCELLED_REF_MARKER in ref:
        return
    new_ref = f"{ref}{CANCELLED_REF_MARKER}{doc.name}"
    try:
        # db_set bypasses document-level validation (cancelled docs are frozen)
        # and writes directly to the DB; we also do NOT bump modified to avoid
        # cluttering audit logs.
        doc.db_set("custom_cybervidya_ref", new_ref, update_modified=False)
    except Exception as e:
        frappe.log_error(
            message=(
                f"Failed to suffix custom_cybervidya_ref on cancel of "
                f"{doc.name} (original ref: {ref!r}): {type(e).__name__}: {e}"
            ),
            title="CyberVidya: on_cancel hook failed",
        )


def free_cancelled_ref_holder(reference: str) -> Optional[str]:
    """Pre-insert safety net: if a CANCELLED JE still holds this reference
    (e.g., it was cancelled before the on_cancel hook existed, or the hook
    crashed), suffix it so the reference becomes free. Returns the suffixed
    name if we modified anything, else None.
    """
    holder = frappe.db.get_value(
        "Journal Entry",
        {"custom_cybervidya_ref": reference, "docstatus": 2},
        "name",
    )
    if not holder:
        return None
    new_ref = f"{reference}{CANCELLED_REF_MARKER}{holder}"
    frappe.db.set_value(
        "Journal Entry", holder, "custom_cybervidya_ref", new_ref,
        update_modified=False,
    )
    return holder


# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------

def send_rejection_alert(reference: str, reason: str, payload: Optional[dict] = None) -> None:
    """Log a rejection to the Error Log and email configured recipients.

    Recipients come from site config key `dux_cybervidya_alert_recipients`
    (list of emails or comma-separated string). If unset, only the Error
    Log entry is written — see CLAUDE.md §12 open item 3."""
    title = f"CyberVidya rejection: {reference or '(no ref)'}"
    body_lines = [
        f"Reference: {reference or '(none)'}",
        f"Reason: {reason}",
    ]
    if payload:
        safe_payload = {k: v for k, v in payload.items() if k != "cmd"}
        body_lines.append(f"Payload: {safe_payload}")
    body = "\n".join(body_lines)

    try:
        frappe.log_error(message=body, title=title)
    except Exception:
        pass

    recipients = _alert_recipients()
    if not recipients:
        return
    try:
        frappe.sendmail(
            recipients=recipients,
            subject=title,
            message=f"<pre>{frappe.utils.escape_html(body)}</pre>",
            now=True,
        )
    except Exception:
        frappe.log_error(
            message=f"Failed to send CyberVidya rejection alert for {reference}",
            title="CyberVidya: alert send failed",
        )


def _alert_recipients() -> list:
    raw = frappe.conf.get("dux_cybervidya_alert_recipients")
    if not raw:
        return []
    if isinstance(raw, str):
        return [r.strip() for r in raw.split(",") if r.strip()]
    if isinstance(raw, list):
        return [str(r).strip() for r in raw if str(r).strip()]
    return []
