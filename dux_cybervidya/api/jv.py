"""Whitelisted endpoint for CyberVidya JV (journal-voucher / inter-entity) posts.

Public method: dux_cybervidya.api.jv.post_daily_jv

Accounting (see CLAUDE.md §3):

    Dr  {account resolved from (jv_code, company) via CyberVidya JV Map}
    Cr  Student Receivable Cybervidya - {ABBR}

A JV settles a student receivable via an inter-entity transfer or a write-off
rather than a bank/cash deposit. The debit account is whatever the global
CyberVidya JV Map routes (jv_code, company) to — a non-group leaf in the same
company as the receivable (one ERPNext Journal Entry is single-company).

Same payload envelope, idempotency mechanics (custom_cybervidya_ref unique DB
constraint + on_cancel suffixing), response shape, and rejection-alert path as
the collection/refund endpoints. A reference uniquely identifies ONE logical
event across all three endpoints.
"""

import frappe

from dux_cybervidya.api.utils import (
    CyberVidyaRejection,
    build_and_submit_je,
    derive_receivable_head,
    free_cancelled_ref_holder,
    resolve_company,
    resolve_jv_account,
    send_rejection_alert,
    validate_jv_payload,
)


@frappe.whitelist(allow_guest=False, methods=["POST"])
def post_daily_jv(**kwargs):
    raw_ref = (kwargs.get("reference") or "").strip() if isinstance(kwargs.get("reference"), str) else ""

    try:
        payload = validate_jv_payload(kwargs)
    except CyberVidyaRejection as e:
        return _reject(raw_ref, e.reason, kwargs)

    reference = payload["reference"]

    # Idempotency: only ACTIVE (docstatus=1) JEs count as "already exists".
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

    # Safety net: free a stale cancelled holder of this reference.
    freed = free_cancelled_ref_holder(reference)
    if freed:
        frappe.db.commit()

    try:
        company = resolve_company(payload["institution"])
        debit_account = resolve_jv_account(payload["jv_code"], company)
        credit_account = derive_receivable_head(company)

        je_name = build_and_submit_je(
            company=company,
            posting_date=payload["collection_date"],
            debit_account=debit_account,
            credit_account=credit_account,
            amount=payload["amount"],
            reference=reference,
            remarks=payload["remarks"] or f"CyberVidya JV {reference}",
        )

    except CyberVidyaRejection as e:
        frappe.db.rollback()
        return _reject(reference, e.reason, kwargs)

    except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
        frappe.db.rollback()
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
            title=f"CyberVidya: unhandled error for JV ref {reference}",
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
