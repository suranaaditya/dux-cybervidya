"""
Read-only controllers for the Daily Fee Collection dashboard Page.

Six whitelisted endpoints, each taking a single `filters` JSON-string argument,
reading `tabJournal Entry` (+ child accounts) for CV-tagged entries only, and
returning JSON-serialisable dicts/lists for the frontend render functions.

Direction is derived from the account lines:
    Student Receivable Cybervidya - {ABBR}  -> collection
    Student Payable Cybervidya - {ABBR}     -> refund
Channel is derived from the counter line:
    Cash Cyber Vidhya - {ABBR}              -> cash   (else bank)

Nothing here writes. See CLAUDE.md §3 and DASHBOARD_CONTEXT.md §3/§4.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, today, getdate, cint

# --- Account-name prefixes — verbatim per CLAUDE.md §3 ----------------------
RECV_PREFIX = "Student Receivable Cybervidya - "
PAY_PREFIX = "Student Payable Cybervidya - "
CASH_PREFIX = "Cash Cyber Vidhya - "

# --- Reference predicates — only JEs we created via API or import -----------
REF_LIKE_LIVE = "CV-%"
REF_LIKE_HIST = "HIST-%"

# --- Trust-group taxonomy — verbatim from DASHBOARD_CONTEXT.md §4 -----------
TRUST_GROUPS = [
    ("ASS",  "Ankush Shikshan Sanstha (ASS)",                       ["GHRCE", "GHRIETN", "GHRILS", "GHRLS"]),
    ("EMF",  "GH Raisoni Educational & Medical Foundation (GHREMF)", ["GHRCEM", "GHRCACS", "GHRPSP"]),
    ("EF",   "GH Raisoni Education Foundation Jalgaon (GHREF)",      ["GHRJCJ", "GHRIBM", "GHRPSJ", "SRWC"]),
    ("RF",   "GH Raisoni Foundation (GHRF)",                         ["GHRSBM", "GHRPSA"]),
    ("CBS",  "Chaitanya Bahuudeshiya Sanstha (CBS)",                 ["GHRIMR"]),
    ("UA",   "GH Raisoni University Amravati (GHRUA)",               ["GHRUA"]),
    ("STUN", "GH Raisoni Skill Tech University Nagpur",              ["GHRSTU"]),
    ("STUP", "GH Raisoni International Skill Tech University Pune",   ["GHRISTU"]),
    ("US",   "GH Raisoni University Saikheda (GHRUS)",               ["GHRUS"]),
]
ACTIVE_CV_CODES = [c for _, _, codes in TRUST_GROUPS for c in codes]   # 18
CODE_TO_GROUP = {c: (k, n) for k, n, codes in TRUST_GROUPS for c in codes}


# ---------------------------------------------------------------------------
# Mapping cache (institution code <-> company <-> abbr), worker-lifetime
# ---------------------------------------------------------------------------
_MAP_CACHE = {}


def _maps():
    """Return (code_to_company, company_to_code, code_to_abbr, company_to_name).
    Built from CyberVidya Account Mapping + Company. Cached per worker;
    refresh_maps() clears it (wired to after_migrate)."""
    if _MAP_CACHE:
        return _MAP_CACHE["data"]
    code_to_company, company_to_code, code_to_abbr = {}, {}, {}
    for m in frappe.get_all("CyberVidya Account Mapping",
                            fields=["name", "company"]):
        code = m.name
        company = m.company
        if not company:
            continue
        abbr = frappe.db.get_value("Company", company, "abbr")
        code_to_company[code] = company
        company_to_code[company] = code
        code_to_abbr[code] = abbr
    data = (code_to_company, company_to_code, code_to_abbr)
    _MAP_CACHE["data"] = data
    return data


def refresh_maps():
    """Clear the mapping cache. Wired to after_migrate in hooks.py."""
    _MAP_CACHE.clear()


# ---------------------------------------------------------------------------
# Filter parsing
# ---------------------------------------------------------------------------
def _parse_filters(filters):
    """Parse JSON-string or dict; apply server-side defaults. Returns a dict."""
    if filters is None:
        filters = {}
    elif isinstance(filters, str):
        filters = json.loads(filters or "{}")
    elif not isinstance(filters, dict):
        filters = dict(filters)

    yest = add_days(today(), -1)   # "yesterday" in site TZ (IST on this site)

    direction = (filters.get("direction") or "both").lower()
    if direction not in ("both", "collections", "refunds"):
        direction = "both"
    channel = (filters.get("channel") or "all").lower()
    if channel not in ("all", "bank", "cash"):
        channel = "all"
    status = (filters.get("status") or "active").lower()
    if status not in ("active", "cancelled", "both"):
        status = "active"
    source = (filters.get("source") or "all").lower()
    if source not in ("all", "live", "historical"):
        source = "all"

    date_from = filters.get("date_from") or yest
    date_to = filters.get("date_to") or yest

    groups = filters.get("trust_groups") or []
    insts = filters.get("institutions") or []
    if isinstance(groups, str):
        groups = [groups]
    if isinstance(insts, str):
        insts = [insts]

    return {
        "direction": direction,
        "channel": channel,
        "status": status,
        "source": source,
        "date_from": str(getdate(date_from)),
        "date_to": str(getdate(date_to)),
        "trust_groups": groups,
        "institutions": insts,
        "q": (filters.get("q") or "").strip(),
        "ledger": (filters.get("ledger") or "").strip(),
        "institution": (filters.get("institution") or "").strip(),
    }


def _allowed_companies(f):
    """Resolve the filter's trust_groups + institutions to a company list.
    Empty result => no restriction (caller treats None as 'all')."""
    code_to_company, _, _ = _maps()
    codes = set(ACTIVE_CV_CODES)
    if f["trust_groups"]:
        want = set()
        for k, _n, cds in TRUST_GROUPS:
            if k in f["trust_groups"]:
                want.update(cds)
        codes &= want
    if f["institutions"]:
        codes &= set(f["institutions"])
    if codes == set(ACTIVE_CV_CODES):
        return None   # no restriction
    return [code_to_company[c] for c in codes if c in code_to_company]


# ---------------------------------------------------------------------------
# Base query — every CV-tagged JE with derived direction/channel/source/status
# ---------------------------------------------------------------------------
def _base_subquery():
    """Return the inner SQL (a parenthesizable subquery body) yielding one row
    per CV-tagged JE with derived columns. No user filters inside.

    The literal LIKE wildcards are doubled (%%) before returning because this
    string is concatenated into a query that carries %s params, and MySQLdb
    treats the whole statement as a printf-style format string."""
    sql = f"""
    SELECT cv.*,
      CASE WHEN cv.recv_acct IS NOT NULL THEN 'collection'
           WHEN cv.pay_acct  IS NOT NULL THEN 'refund' END           AS direction,
      CASE WHEN cv.counter_acct LIKE '{CASH_PREFIX}%' THEN 'cash'
           ELSE 'bank' END                                           AS channel,
      CASE WHEN cv.ref LIKE '{REF_LIKE_HIST}' THEN 'historical'
           ELSE 'live' END                                           AS source,
      CASE WHEN cv.docstatus = 1 THEN 'Active' ELSE 'Cancelled' END  AS status
    FROM (
      SELECT
        je.name, je.company, je.posting_date, je.total_debit AS amount,
        je.custom_cybervidya_ref AS ref, je.docstatus, je.user_remark, je.creation,
        MAX(CASE WHEN jea.account LIKE '{RECV_PREFIX}%' THEN jea.account END) AS recv_acct,
        MAX(CASE WHEN jea.account LIKE '{PAY_PREFIX}%'  THEN jea.account END) AS pay_acct,
        MAX(CASE WHEN jea.account NOT LIKE '{RECV_PREFIX}%'
                  AND jea.account NOT LIKE '{PAY_PREFIX}%'
                 THEN jea.account END)                               AS counter_acct
      FROM `tabJournal Entry` je
      JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
      WHERE je.custom_cybervidya_ref IS NOT NULL
        AND (je.custom_cybervidya_ref LIKE '{REF_LIKE_LIVE}'
             OR je.custom_cybervidya_ref LIKE '{REF_LIKE_HIST}')
      GROUP BY je.name
    ) cv
    HAVING direction IS NOT NULL
    """
    return sql.replace("%", "%%")


def _scoped(f, *, select, extra_where=None, apply_date=True, group_by=None,
            order_by=None, select_params=None, extra_params=None,
            ignore_direction=False, ignore_status=False):
    """Compose a query on top of the base subquery applying standard filters.

    Param ordering matters: `select_params` bind to %s placeholders inside the
    SELECT clause (which precedes WHERE) and so are prepended; `extra_params`
    bind to `extra_where` (the last WHERE condition) and so are appended."""
    where, p = [], list(select_params or [])

    if apply_date:
        where.append("t.posting_date BETWEEN %s AND %s")
        p += [f["date_from"], f["date_to"]]

    if not ignore_direction and f["direction"] != "both":
        want = "collection" if f["direction"] == "collections" else "refund"
        where.append("t.direction = %s")
        p.append(want)

    if f["channel"] != "all":
        where.append("t.channel = %s")
        p.append(f["channel"])

    if f["source"] != "all":
        where.append("t.source = %s")
        p.append(f["source"])

    if not ignore_status:
        if f["status"] == "active":
            where.append("t.docstatus = 1")
        elif f["status"] == "cancelled":
            where.append("t.docstatus = 2")

    companies = _allowed_companies(f)
    if companies is not None:
        if not companies:
            where.append("1=0")
        else:
            where.append("t.company IN (%s)" % ", ".join(["%s"] * len(companies)))
            p += companies

    if extra_where:
        where.append(extra_where)
        p += list(extra_params or [])

    sql = f"SELECT {select} FROM ({_base_subquery()}) t"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if group_by:
        sql += " GROUP BY " + group_by
    if order_by:
        sql += " ORDER BY " + order_by
    return sql, p


def _guard():
    if not frappe.has_permission("Journal Entry", "read"):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


# ---------------------------------------------------------------------------
# 4.3 summary
# ---------------------------------------------------------------------------
@frappe.whitelist()
def summary(filters=None):
    _guard()
    f = _parse_filters(filters)

    # collections + refunds respect everything EXCEPT we compute both sides
    # then honour the direction filter for display.
    sql, p = _scoped(
        f,
        select="t.direction AS direction, COUNT(*) AS cnt, "
               "COALESCE(SUM(t.amount),0) AS total",
        ignore_direction=True,
        group_by="t.direction",
    )
    rows = frappe.db.sql(sql, p, as_dict=True)
    by = {r.direction: r for r in rows}
    coll = by.get("collection")
    refs = by.get("refund")
    c_total = int(coll.total) if coll else 0
    c_count = int(coll.cnt) if coll else 0
    r_total = int(refs.total) if refs else 0
    r_count = int(refs.cnt) if refs else 0

    if f["direction"] == "refunds":
        c_total = c_count = 0
    if f["direction"] == "collections":
        r_total = r_count = 0

    # cancelled-in-scope: ignore the status filter, count docstatus=2
    csql, cp = _scoped(
        f,
        select="COUNT(*) AS cnt, COALESCE(SUM(t.amount),0) AS total",
        ignore_status=True,
        ignore_direction=True,
        extra_where="t.docstatus = 2",
    )
    crow = frappe.db.sql(csql, cp, as_dict=True)
    cancelled_total = int(crow[0].total) if crow and crow[0].total else 0
    cancelled_count = int(crow[0].cnt) if crow else 0

    return {
        "collections": {"total": c_total, "count": c_count},
        "refunds": {"total": r_total, "count": r_count},
        "net": c_total - r_total,
        "cancelled": {"total": cancelled_total, "count": cancelled_count},
    }


# ---------------------------------------------------------------------------
# 4.4 daily
# ---------------------------------------------------------------------------
@frappe.whitelist()
def daily(filters=None):
    _guard()
    f = _parse_filters(filters)
    sql, p = _scoped(
        f,
        select="t.posting_date AS d, "
               "COALESCE(SUM(CASE WHEN t.direction='collection' THEN t.amount END),0) AS coll, "
               "COALESCE(SUM(CASE WHEN t.direction='refund' THEN t.amount END),0) AS refs, "
               "COUNT(*) AS cnt",
        ignore_direction=True,
        group_by="t.posting_date",
    )
    rows = {str(r.d): r for r in frappe.db.sql(sql, p, as_dict=True)}

    out = []
    d, end = getdate(f["date_from"]), getdate(f["date_to"])
    while d <= end:
        ds = str(d)
        r = rows.get(ds)
        coll = int(r.coll) if r else 0
        refs = int(r.refs) if r else 0
        cnt = int(r.cnt) if r else 0
        # honour direction filter for the displayed series
        if f["direction"] == "refunds":
            coll = 0
        if f["direction"] == "collections":
            refs = 0
        out.append({"date": ds, "collections": coll, "refunds": refs,
                    "net": coll - refs, "count": cnt})
        d = add_days(d, 1)
    return out


# ---------------------------------------------------------------------------
# 4.5 inst_table
# ---------------------------------------------------------------------------
@frappe.whitelist()
def inst_table(filters=None):
    _guard()
    f = _parse_filters(filters)
    _, company_to_code, code_to_abbr = _maps()
    sql, p = _scoped(
        f,
        select="t.company AS company, "
               "COALESCE(SUM(CASE WHEN t.direction='collection' THEN t.amount END),0) AS coll, "
               "COALESCE(SUM(CASE WHEN t.direction='refund' THEN t.amount END),0) AS refs, "
               "COUNT(*) AS cnt, MAX(t.creation) AS last_activity",
        ignore_direction=True,
        group_by="t.company",
    )
    out = []
    for r in frappe.db.sql(sql, p, as_dict=True):
        code = company_to_code.get(r.company)
        if not code:
            continue
        gk, gn = CODE_TO_GROUP.get(code, ("", ""))
        coll = int(r.coll)
        refs = int(r.refs)
        if f["direction"] == "refunds":
            coll = 0
        if f["direction"] == "collections":
            refs = 0
        out.append({
            "code": code, "company": r.company,
            "abbr": code_to_abbr.get(code),
            "group_key": gk, "group_name": gn,
            "collections": coll, "refunds": refs, "net": coll - refs,
            "count": int(r.cnt),
            "last_activity": r.last_activity.isoformat() if r.last_activity else None,
        })
    out.sort(key=lambda x: x["net"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# 4.6 throughflow  (fixed windows, independent of the filter bar's date range)
# ---------------------------------------------------------------------------
def _pooled_counts():
    """ledger account name -> count of distinct institutions sharing it."""
    rows = frappe.db.sql("""
        SELECT bank_account AS acct, COUNT(DISTINCT parent) AS n
        FROM `tabCyberVidya Bank Map`
        GROUP BY bank_account
    """, as_dict=True)
    return {r.acct: int(r.n) for r in rows}


@frappe.whitelist()
def throughflow(filters=None):
    _guard()
    f = _parse_filters(filters)   # honours direction/channel/source/group/inst, NOT date
    _, company_to_code, code_to_abbr = _maps()
    pooled = _pooled_counts()

    yest = add_days(today(), -1)
    wk_start = add_days(yest, -6)
    mo_start = add_days(yest, -29)
    spark_start = add_days(yest, -13)

    # net throughflow per (company, counter ledger), active JEs only, all dates,
    # plus the windowed sums. Signed: collection +, refund -.
    sql, p = _scoped(
        f,
        select=(
            "t.company AS company, t.counter_acct AS ledger, t.channel AS channel, "
            "COALESCE(SUM(CASE WHEN t.posting_date=%s THEN "
            "  (CASE WHEN t.direction='collection' THEN t.amount ELSE -t.amount END) END),0) AS yday, "
            "COALESCE(SUM(CASE WHEN t.posting_date BETWEEN %s AND %s THEN "
            "  (CASE WHEN t.direction='collection' THEN t.amount ELSE -t.amount END) END),0) AS wk, "
            "COALESCE(SUM(CASE WHEN t.posting_date BETWEEN %s AND %s THEN "
            "  (CASE WHEN t.direction='collection' THEN t.amount ELSE -t.amount END) END),0) AS mo"
        ),
        apply_date=False,
        ignore_direction=True,
        extra_where="t.docstatus = 1",
        group_by="t.company, t.counter_acct, t.channel",
        select_params=[yest, wk_start, yest, mo_start, yest],
    )
    rows = frappe.db.sql(sql, p, as_dict=True)

    # 14-day spark buckets per (company, ledger)
    spark_sql, sp = _scoped(
        f,
        select="t.company AS company, t.counter_acct AS ledger, t.posting_date AS d, "
               "COALESCE(SUM(CASE WHEN t.direction='collection' THEN t.amount ELSE -t.amount END),0) AS v",
        apply_date=False,
        ignore_direction=True,
        extra_where="t.docstatus = 1 AND t.posting_date BETWEEN %s AND %s",
        group_by="t.company, t.counter_acct, t.posting_date",
        extra_params=[spark_start, yest],
    )
    spark_map = {}
    for r in frappe.db.sql(spark_sql, sp, as_dict=True):
        spark_map.setdefault((r.company, r.ledger), {})[str(r.d)] = int(r.v)

    spark_days = [str(add_days(spark_start, i)) for i in range(14)]
    out = []
    for r in rows:
        code = company_to_code.get(r.company)
        sm = spark_map.get((r.company, r.ledger), {})
        out.append({
            "code": code, "abbr": code_to_abbr.get(code), "company": r.company,
            "ledger": r.ledger, "channel": r.channel,
            "is_pooled": pooled.get(r.ledger, 0) > 1,
            "pooled_count": pooled.get(r.ledger, 0),
            "yesterday": int(r.yday), "week": int(r.wk), "month": int(r.mo),
            "spark": [sm.get(dd, 0) for dd in spark_days],
        })
    out.sort(key=lambda x: x["month"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# 4.7 feed  (+ 4.8 cancelled-replacement detection)
# ---------------------------------------------------------------------------
@frappe.whitelist()
def feed(filters=None, limit=50):
    _guard()
    f = _parse_filters(filters)
    _, company_to_code, code_to_abbr = _maps()
    limit = max(1, min(cint(limit) or 50, 100))

    extra_where = None
    params = []
    if f["q"]:
        extra_where = "t.ref LIKE %s"
        params = [f"%{f['q']}%"]
    elif f["ledger"]:
        # ledger drawer: scope to one counter ledger (+ optional institution)
        extra_where = "t.counter_acct = %s"
        params = [f["ledger"]]
        if f["institution"]:
            code_to_company, _, _ = _maps()
            comp = code_to_company.get(f["institution"])
            if comp:
                extra_where += " AND t.company = %s"
                params.append(comp)

    sql, p = _scoped(
        f,
        select="t.name, t.ref, t.company, t.direction, t.channel, t.counter_acct AS ledger, "
               "t.amount, t.status, t.source, t.creation, t.posting_date, t.docstatus",
        extra_where=extra_where,
        extra_params=params,
        order_by="t.creation DESC, t.name DESC",
    )
    sql += " LIMIT %s" % (limit + 0)
    rows = frappe.db.sql(sql, p, as_dict=True)

    out = []
    for r in rows:
        code = company_to_code.get(r.company)
        replaced_by = None
        if r.docstatus == 2 and r.ref:
            base = r.ref.split("__CANCELLED__")[0]
            sib = frappe.db.sql("""
                SELECT custom_cybervidya_ref AS ref
                FROM `tabJournal Entry`
                WHERE docstatus = 1 AND custom_cybervidya_ref LIKE %s
                ORDER BY creation DESC LIMIT 1
            """, (f"{base}-R%",), as_dict=True)
            if sib:
                replaced_by = sib[0].ref
        out.append({
            "name": r.name, "ref": r.ref, "code": code,
            "abbr": code_to_abbr.get(code), "company": r.company,
            "direction": r.direction, "channel": r.channel, "ledger": r.ledger,
            "amount": int(r.amount), "status": r.status, "source": r.source,
            "dt": r.creation.isoformat() if r.creation else None,
            "posting_date": str(r.posting_date),
            "replaced_by_ref": replaced_by,
        })
    return out
