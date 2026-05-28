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
CASH_HEAD_TEMPLATE = "Cash Cyber Vidhya - {abbr}"

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


def derive_receivable_head(company: str) -> str:
    abbr = _company_abbr(company)
    head = RECEIVABLE_HEAD_TEMPLATE.format(abbr=abbr)
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

    je.append("accounts", {
        "account": debit_account,
        "debit_in_account_currency": amount,
        "credit_in_account_currency": 0,
    })
    je.append("accounts", {
        "account": credit_account,
        "debit_in_account_currency": 0,
        "credit_in_account_currency": amount,
    })

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
