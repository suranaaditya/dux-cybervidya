"""Whitelisted endpoint for CyberVidya 'other fees' posts — head-based
collections booked into the college's parent TRUST/SANSTHA company.

Public method: dux_cybervidya.api.other_fees.post_other_fees

Accounting (see CLAUDE.md §14):

    Dr  {bank or cash leaf in the SANSTHA company}
    Cr  {fee-head income leaf in the SANSTHA company}

A college's "other fee" (Prospectus, Exam, Alumni, Convocation, ...) is booked
directly as income into the college's parent sanstha company — NOT the college
company (an ERPNext Journal Entry is single-company). The bank/cash debit ledger
and the fee-head income credit ledger are both resolved server-side in that
sanstha via CyberVidya Other Fees Mapping. This is immediate income recognition
(contrast: the main collection flow credits a Student Receivable and defers
income to a year-end JE).

Same payload envelope, idempotency mechanics (custom_cybervidya_ref unique DB
constraint + on_cancel suffixing), response shape, and rejection-alert path as
the collection / refund / jv endpoints. References use an `OF-` prefix by
convention so they share the idempotency field without colliding with the
collection/refund `CV-` or historical `HIST-` namespaces.
"""

import frappe

from dux_cybervidya.api.utils import (
    CyberVidyaRejection,
    build_and_submit_je,
    free_cancelled_ref_holder,
    resolve_fee_account,
    resolve_other_fees_ledger,
    resolve_sanstha_company,
    send_rejection_alert,
    validate_other_fees_payload,
)


@frappe.whitelist(allow_guest=False, methods=["POST"])
def post_other_fees(**kwargs):
    raw_ref = (kwargs.get("reference") or "").strip() if isinstance(kwargs.get("reference"), str) else ""

    try:
        payload = validate_other_fees_payload(kwargs)
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
        sanstha = resolve_sanstha_company(payload["institution"])
        debit_account = resolve_other_fees_ledger(
            payload["institution"],
            payload["collection_type"],
            payload["bank_account_head"],
            sanstha,
        )
        credit_account = resolve_fee_account(
            payload["institution"], payload["fee_head"], sanstha
        )

        je_name = build_and_submit_je(
            company=sanstha,
            posting_date=payload["collection_date"],
            debit_account=debit_account,
            credit_account=credit_account,
            amount=payload["amount"],
            reference=reference,
            remarks=(
                payload["remarks"]
                or f"CyberVidya other-fee {payload['fee_head']} "
                f"[{payload['institution']}] {reference}"
            ),
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
            title=f"CyberVidya: unhandled error for other-fee ref {reference}",
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
