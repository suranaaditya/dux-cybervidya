"""Whitelisted endpoint for CyberVidya end-of-day fee-refund posts.

Public method: dux_cybervidya.api.refund.post_daily_refund

Accounting MIRROR of post_daily_collection (see CLAUDE.md §3 and §6):

    Bank refund: Dr Student Payable Cybervidya - {ABBR}  / Cr {mapped bank leaf}
    Cash refund: Dr Student Payable Cybervidya - {ABBR}  / Cr Cash Cyber Vidhya - {ABBR}

Same payload shape, same idempotency mechanics (custom_cybervidya_ref unique
DB constraint + on_cancel suffixing), same response envelope, same rejection
alert path. The CyberVidya Account Mapping rows are direction-agnostic — the
institution + bank rows resolve the same way regardless of money direction.

A reference uniquely identifies ONE logical event across both endpoints; a
double-post (collection + refund with the same ref) is naturally prevented by
the unique DB constraint on custom_cybervidya_ref.

Note: ~60% of the body intentionally duplicates collection.py. The two flows
are conceptually distinct (money out vs money in), the endpoint surface is
small, and explicit duplication reads better here than a branchy shared
helper. Do not prematurely refactor.
"""

import frappe

from dux_cybervidya.api.utils import (
    CyberVidyaRejection,
    build_and_submit_je,
    derive_cash_head,
    derive_payable_head,
    free_cancelled_ref_holder,
    resolve_bank_ledger,
    resolve_company,
    send_rejection_alert,
    validate_payload,
)


@frappe.whitelist(allow_guest=False, methods=["POST"])
def post_daily_refund(**kwargs):
    raw_ref = (kwargs.get("reference") or "").strip() if isinstance(kwargs.get("reference"), str) else ""

    try:
        payload = validate_payload(kwargs)
    except CyberVidyaRejection as e:
        return _reject(raw_ref, e.reason, kwargs)

    reference = payload["reference"]

    # Idempotency: only ACTIVE (docstatus=1) JEs count as "already exists".
    # Cancelled JEs (docstatus=2) have zero ledger impact, so a retry should
    # be allowed to create a fresh JE. See utils.on_journal_entry_cancel
    # which suffixes the cancelled JE's ref to release the unique constraint.
    existing = frappe.db.get_value(
        "Journal Entry",
        {"custom_cybervidya_ref": reference, "docstatus": 1},
        "name",
    )
    if existing:
        return {
            "status": "already_exists",
            "journal_entry": existing,
            "reference": reference,
        }

    # Safety net: if a CANCELLED JE still holds this reference (e.g. it was
    # cancelled before the on_cancel hook existed, or the hook crashed),
    # suffix it now so the unique constraint releases. The hook handles new
    # cancellations automatically; this only kicks in for legacy/stale data.
    freed = free_cancelled_ref_holder(reference)
    if freed:
        frappe.db.commit()  # release the index entry before our insert

    try:
        company = resolve_company(payload["institution"])

        # MIRROR of collection: for a refund the bank/cash leaf is CREDITED
        # (money leaving), and the Payable head is DEBITED (liability cleared).
        if payload["collection_type"] == "bank":
            credit_account = resolve_bank_ledger(
                institution_code=payload["institution"],
                bank_code=payload["bank"],
                company=company,
            )
        else:
            credit_account = derive_cash_head(company)

        debit_account = derive_payable_head(company)

        je_name = build_and_submit_je(
            company=company,
            posting_date=payload["collection_date"],
            debit_account=debit_account,
            credit_account=credit_account,
            amount=payload["amount"],
            reference=reference,
            remarks=payload["remarks"],
        )

    except CyberVidyaRejection as e:
        frappe.db.rollback()
        return _reject(reference, e.reason, kwargs)

    except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
        frappe.db.rollback()
        # Re-read the holder to decide what to return.
        holder = frappe.db.get_value(
            "Journal Entry",
            {"custom_cybervidya_ref": reference},
            ["name", "docstatus"],
            as_dict=True,
        )
        if holder and holder.docstatus == 1:
            return {
                "status": "already_exists",
                "journal_entry": holder.name,
                "reference": reference,
            }
        if holder and holder.docstatus == 2:
            # Cancelled JE still holds the ref (race with cancellation, or
            # the on_cancel hook hasn't run). Surface a precise rejection so
            # the operator can investigate; do NOT silently suffix here to
            # avoid masking deeper concurrency issues.
            return _reject(
                reference,
                f"Reference is held by a cancelled Journal Entry ({holder.name}). "
                f"Retry once the on_cancel hook has freed the reference.",
                kwargs,
            )
        return _reject(
            reference,
            "Duplicate reference race lost but no matching JE found on re-read.",
            kwargs,
        )

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(
            message=frappe.get_traceback(),
            title=f"CyberVidya: unhandled error for ref {reference}",
        )
        send_rejection_alert(
            reference, f"Unhandled error: {type(e).__name__}: {e}", kwargs
        )
        return {
            "status": "rejected",
            "reference": reference,
            "reason": f"Unhandled error: {type(e).__name__}",
        }

    return {
        "status": "created",
        "journal_entry": je_name,
        "reference": reference,
    }


def _reject(reference: str, reason: str, payload: dict) -> dict:
    send_rejection_alert(reference, reason, payload)
    return {
        "status": "rejected",
        "reference": reference,
        "reason": reason,
    }
