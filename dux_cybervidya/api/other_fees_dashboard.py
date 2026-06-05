"""
Read-only controllers for the Other-Fees / Sanstha Collection report Page.

Other-fee JEs credit an INCOME leaf (under "CyberVidya Other Fees - {abbr}") and
debit a bank/cash leaf, all in the SANSTHA company. They carry NO Student
Receivable/Payable line, so the daily-collection dashboard (api/dashboard.py),
which keys on those, excludes them. This report keys on the OF-/HISTOF-
reference namespace instead.

College identity is recovered from the JE user_remark (which embeds the college
code as the first [bracketed] token), since the posting itself lives in the
parent sanstha company. Nothing here writes. See CLAUDE.md §14.
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import add_days, today, getdate, cint

REF_LIKE_LIVE = "OF-%"
REF_LIKE_HIST = "HISTOF-%"
_BRACKET = re.compile(r"\[([^\]]+)\]")

_OF_MAP_CACHE = {}


# ---------------------------------------------------------------------------
# Mapping cache (college code -> sanstha company / abbr), worker-lifetime
# ---------------------------------------------------------------------------
def _of_maps():
    """(inst_to_sanstha, inst_to_abbr, sansthas[{company,abbr}])."""
    if _OF_MAP_CACHE:
        return _OF_MAP_CACHE["data"]
    inst_to_sanstha, inst_to_abbr, sansthas = {}, {}, {}
    for m in frappe.get_all("CyberVidya Other Fees Mapping",
                            fields=["name", "sanstha_company"]):
        if not m.sanstha_company:
            continue
        abbr = frappe.db.get_value("Company", m.sanstha_company, "abbr")
        inst_to_sanstha[m.name] = m.sanstha_company
        inst_to_abbr[m.name] = abbr
        sansthas[m.sanstha_company] = abbr
    data = (inst_to_sanstha, inst_to_abbr,
            [{"company": c, "abbr": a} for c, a in sorted(sansthas.items())])
    _OF_MAP_CACHE["data"] = data
    return data


def refresh_other_fees_maps():
    """Clear the cache. Wired to after_migrate in hooks.py."""
    _OF_MAP_CACHE.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _guard():
    if not frappe.has_permission("Journal Entry", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def _institution(remark):
    if not remark:
        return None
    m = _BRACKET.search(remark)
    return m.group(1).strip() if m else None


def _fee_head_label(account):
    if not account:
        return None
    return account.rsplit(" - ", 1)[0]


def _parse_filters(filters):
    if filters is None:
        filters = {}
    elif isinstance(filters, str):
        filters = json.loads(filters or "{}")
    elif not isinstance(filters, dict):
        filters = dict(filters)

    channel = (filters.get("channel") or "all").lower()
    if channel not in ("all", "bank", "cash"):
        channel = "all"
    source = (filters.get("source") or "all").lower()
    if source not in ("all", "live", "historical"):
        source = "all"
    status = (filters.get("status") or "active").lower()
    if status not in ("active", "cancelled", "both"):
        status = "active"

    date_to = filters.get("date_to") or today()
    date_from = filters.get("date_from") or add_days(getdate(date_to), -180)

    sansthas = filters.get("sansthas") or []
    insts = filters.get("institutions") or []
    if isinstance(sansthas, str):
        sansthas = [sansthas]
    if isinstance(insts, str):
        insts = [insts]

    return {
        "channel": channel, "source": source, "status": status,
        "date_from": str(getdate(date_from)), "date_to": str(getdate(date_to)),
        "sansthas": sansthas, "institutions": insts,
        "fee_head": (filters.get("fee_head") or "").strip(),
        "q": (filters.get("q") or "").strip(),
    }


def _fetch(f, status_override=None):
    """One SQL query + python enrichment/filtering. Returns a list of row dicts.

    The dataset (institution-level, per-day) is small, so we fetch the scoped
    rows once and aggregate in python — channel, source, college and fee-head
    are all derived per row."""
    _, inst_to_abbr, _s = _of_maps()
    status = status_override or f["status"]

    conds = [
        # Literal LIKE wildcards are DOUBLED (%%): frappe.db.sql is called with
        # params, so MySQLdb treats the whole query as a printf format string
        # (a single %' is read as a bad format spec). Param VALUES below keep
        # single % since they are passed as args, not interpolated into the SQL.
        "(je.custom_cybervidya_ref LIKE 'OF-%%' "
        "OR je.custom_cybervidya_ref LIKE 'HISTOF-%%')",
        "je.posting_date BETWEEN %s AND %s",
    ]
    params = [f["date_from"], f["date_to"]]
    if status == "active":
        conds.append("je.docstatus = 1")
    elif status == "cancelled":
        conds.append("je.docstatus = 2")
    if f["sansthas"]:
        conds.append("je.company IN (%s)" % ", ".join(["%s"] * len(f["sansthas"])))
        params += f["sansthas"]
    if f["q"]:
        conds.append("je.custom_cybervidya_ref LIKE %s")
        params.append(f"%{f['q']}%")
    where = " AND ".join(conds)

    sql = f"""
        SELECT cv.*, ac.account_type AS dr_type
        FROM (
          SELECT je.name, je.company, je.posting_date, je.total_debit AS amount,
                 je.custom_cybervidya_ref AS ref, je.docstatus, je.user_remark, je.creation,
                 MAX(CASE WHEN jea.credit_in_account_currency > 0 THEN jea.account END) AS income_acct,
                 MAX(CASE WHEN jea.debit_in_account_currency  > 0 THEN jea.account END) AS channel_acct
          FROM `tabJournal Entry` je
          JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
          WHERE {where}
          GROUP BY je.name
        ) cv
        LEFT JOIN `tabAccount` ac ON ac.name = cv.channel_acct
    """
    rows = frappe.db.sql(sql, params, as_dict=True)

    out = []
    for r in rows:
        source = "historical" if (r.ref or "").startswith("HISTOF-") else "live"
        channel = "cash" if (r.dr_type == "Cash") else "bank"
        inst = _institution(r.user_remark)
        fee_head = _fee_head_label(r.income_acct)
        if f["source"] != "all" and source != f["source"]:
            continue
        if f["channel"] != "all" and channel != f["channel"]:
            continue
        if f["institutions"] and inst not in f["institutions"]:
            continue
        if f["fee_head"] and (not fee_head or f["fee_head"].lower() not in fee_head.lower()):
            continue
        out.append({
            "name": r.name, "company": r.company,
            "abbr": inst_to_abbr.get(inst),
            "posting_date": str(r.posting_date), "amount": int(r.amount or 0),
            "ref": r.ref, "docstatus": r.docstatus,
            "status": "Active" if r.docstatus == 1 else "Cancelled",
            "source": source, "channel": channel, "institution": inst,
            "income_acct": r.income_acct, "fee_head": fee_head,
            "ledger": r.channel_acct,
            "dt": r.creation.isoformat() if r.creation else None,
        })
    return out


# ---------------------------------------------------------------------------
# Controllers
# ---------------------------------------------------------------------------
@frappe.whitelist()
def options():
    """Filter-population helper: the sansthas + colleges known to the module."""
    _guard()
    inst_to_sanstha, inst_to_abbr, sansthas = _of_maps()
    insts = [{"code": c, "sanstha": s, "abbr": inst_to_abbr.get(c)}
             for c, s in sorted(inst_to_sanstha.items())]
    return {"sansthas": sansthas, "institutions": insts}


@frappe.whitelist()
def summary(filters=None):
    _guard()
    f = _parse_filters(filters)
    rows = _fetch(f)
    total = sum(r["amount"] for r in rows)
    live = [r for r in rows if r["source"] == "live"]
    hist = [r for r in rows if r["source"] == "historical"]
    bank = [r for r in rows if r["channel"] == "bank"]
    cash = [r for r in rows if r["channel"] == "cash"]
    canc = _fetch(f, status_override="cancelled")
    return {
        "total": total, "count": len(rows),
        "live": {"total": sum(r["amount"] for r in live), "count": len(live)},
        "historical": {"total": sum(r["amount"] for r in hist), "count": len(hist)},
        "bank": {"total": sum(r["amount"] for r in bank), "count": len(bank)},
        "cash": {"total": sum(r["amount"] for r in cash), "count": len(cash)},
        "cancelled": {"total": sum(r["amount"] for r in canc), "count": len(canc)},
        "sansthas": len({r["company"] for r in rows}),
        "colleges": len({r["institution"] for r in rows if r["institution"]}),
        "heads": len({r["fee_head"] for r in rows if r["fee_head"]}),
    }


def _group(rows, keyfn):
    agg = {}
    for r in rows:
        k = keyfn(r)
        if k is None:
            k = "—"
        b = agg.setdefault(k, {"total": 0, "count": 0})
        b["total"] += r["amount"]
        b["count"] += 1
    return agg


@frappe.whitelist()
def by_sanstha(filters=None):
    _guard()
    rows = _fetch(_parse_filters(filters))
    agg = {}
    for r in rows:
        b = agg.setdefault(r["company"], {"total": 0, "count": 0})
        b["total"] += r["amount"]
        b["count"] += 1
    out = [{"company": c, "total": v["total"], "count": v["count"]} for c, v in agg.items()]
    out.sort(key=lambda x: x["total"], reverse=True)
    return out


@frappe.whitelist()
def by_fee_head(filters=None):
    _guard()
    rows = _fetch(_parse_filters(filters))
    agg = _group(rows, lambda r: r["fee_head"])
    out = [{"fee_head": k, "total": v["total"], "count": v["count"]} for k, v in agg.items()]
    out.sort(key=lambda x: x["total"], reverse=True)
    return out


@frappe.whitelist()
def by_college(filters=None):
    _guard()
    f = _parse_filters(filters)
    inst_to_sanstha, _a, _s = _of_maps()
    rows = _fetch(f)
    agg = {}
    for r in rows:
        k = r["institution"] or "—"
        b = agg.setdefault(k, {"total": 0, "count": 0})
        b["total"] += r["amount"]
        b["count"] += 1
    out = [{"institution": k, "sanstha": inst_to_sanstha.get(k), "total": v["total"], "count": v["count"]}
           for k, v in agg.items()]
    out.sort(key=lambda x: x["total"], reverse=True)
    return out


@frappe.whitelist()
def by_channel(filters=None):
    _guard()
    rows = _fetch(_parse_filters(filters))
    agg = _group(rows, lambda r: r["channel"])
    return [{"channel": k, "total": v["total"], "count": v["count"]} for k, v in agg.items()]


@frappe.whitelist()
def daily(filters=None):
    _guard()
    f = _parse_filters(filters)
    rows = _fetch(f)
    by = {}
    for r in rows:
        b = by.setdefault(r["posting_date"], {"total": 0, "count": 0})
        b["total"] += r["amount"]
        b["count"] += 1
    out = []
    d, end = getdate(f["date_from"]), getdate(f["date_to"])
    # cap the gap-fill so a huge range can't explode the payload
    guard = 0
    while d <= end and guard < 1000:
        ds = str(d)
        b = by.get(ds, {"total": 0, "count": 0})
        out.append({"date": ds, "total": b["total"], "count": b["count"]})
        d = add_days(d, 1)
        guard += 1
    return out


@frappe.whitelist()
def reconcile(filters=None):
    """Per-college live/historical split — ties back to the source Excel per sheet."""
    _guard()
    f = _parse_filters(filters)
    inst_to_sanstha, _a, _s = _of_maps()
    rows = _fetch(f)
    agg = {}
    for r in rows:
        k = r["institution"] or "—"
        b = agg.setdefault(k, {"live": 0, "historical": 0, "count": 0})
        b[r["source"]] += r["amount"]
        b["count"] += 1
    out = [{"institution": k, "sanstha": inst_to_sanstha.get(k),
            "live": v["live"], "historical": v["historical"],
            "total": v["live"] + v["historical"], "count": v["count"]}
           for k, v in agg.items()]
    out.sort(key=lambda x: x["total"], reverse=True)
    return out


@frappe.whitelist()
def feed(filters=None, limit=60):
    _guard()
    f = _parse_filters(filters)
    limit = max(1, min(cint(limit) or 60, 200))
    rows = _fetch(f)
    rows.sort(key=lambda r: (r["dt"] or "", r["name"]), reverse=True)
    return rows[:limit]
