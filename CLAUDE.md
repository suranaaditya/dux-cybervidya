# Dux CyberVidya — Project Context (CLAUDE.md)

> Drop this file at the repo root. Read it in full at the start of every Claude Code
> session before writing or changing any code. It is the authoritative design — do
> not relitigate decisions recorded here; if something seems wrong, flag it, don't
> silently change it.

App name: **`dux_cybervidya`** (Python package — underscore form used throughout paths below)
Owner: Aditya Surana — Dux DigiTech
GitHub: `suranaaditya/dux-cybervidya` — https://github.com/suranaaditya/dux-cybervidya
(note: repo URL uses a hyphen; the inner Python module stays underscore)

---

## 1. What this app does

Receives **end-of-day fee-collection** data from **CyberVidya** (RGI Group's academic /
fee system) and records it in **ERPNext v16**. CyberVidya calls in; ERPNext is the
receiver. For each collection record, ERPNext posts **one aggregated Journal Entry**.

Integration pattern (**locked**): a single **whitelisted endpoint** receives a **thin
payload**; **all** logic runs server-side. CyberVidya never knows any ERPNext account
name. If the COA changes, only this app changes — their payload is untouched.

Student-level detail stays in CyberVidya. This app does NOT handle billing/demand,
year-end income recognition, or reconciliation automation (see §11 Out of scope).

---

## 2. Servers, sites, dev workflow

| | |
|---|---|
| Dev server | `ssh frappe@187.127.132.58` |
| Dev site | `erp.jewonline.in` |
| Bench | `~/frappe-bench` |
| App path (dev) | `~/frappe-bench/apps/dux_cybervidya` |
| Production | Frappe Cloud — **`ghraisoni.frappe.cloud`** (the 59-company accounting instance) |

**Dev quirks (important, costly to relearn — verified 2026-05-25):**

- Dev bench runs under **supervisor** (gunicorn `--preload`, 3 workers; the master's
  parent is supervisord). There is no `bench start` / honcho / tmux session, despite
  the Procfile listing `bench serve`. **Do NOT run `bench restart` on dev** — for
  Python changes, SIGTERM the gunicorn master instead (see next bullet).
- After a **Python code change** to any app, gunicorn workers will keep running stale
  code, because `--preload` imports the application once at master start and workers
  fork from that image. Two steps to land the change:
  1. `bench --site erp.jewonline.in clear-cache`
  2. SIGTERM the gunicorn master — supervisor respawns it in ~2s:
     ```bash
     SUP=$(pgrep -x supervisord | head -1)
     MASTER=$(ps -ef | awk -v sup="$SUP" '/gunicorn -b 127\.0\.0\.1:8000/ && !/grep/ && $3==sup {print $2}')
     kill -TERM "$MASTER"
     ```
- After a **DocType / fixture / JSON-only** change, `bench migrate` + `clear-cache`
  is enough — no master restart needed.
- DocType creation and ad-hoc data operations are most reliable via **bench console**.
  Pipe scripts via `python ... < file` rather than heredocs — bench console (IPython)
  ends paste-blocks on blank lines and will truncate multi-line scripts.
- Code changes flow: **Claude Code locally → git push → pull on dev → migrate
  → clear-cache → SIGTERM gunicorn master (only if `.py` changed)**.
- Frappe Pages need underscores, not hyphens, in directory names (N/A here, but a
  known trap).

**Build/commit discipline:**

- Work on branch **`feat/cybervidya-integration`** off the default branch. Never push
  directly to `main`/`version-1`. **Ask before committing.**
- State what will change before any bulk/destructive operation.

---

## 3. Accounting model (LOCKED)

One Journal Entry per **(company, channel, date)**. Channel = a specific bank account, OR cash.
One CyberVidya record = one request = one JE.

| Channel | Debit (Dr) | Credit (Cr) |
|---|---|---|
| Bank | `{mapped bank leaf ledger}` | `Student Receivable Cybervidya - {ABBR}` |
| Cash | `Cash Cyber Vidhya - {ABBR}` | `Student Receivable Cybervidya - {ABBR}` |

**Exact account-name strings — use VERBATIM (confirmed present in all 59 companies as
non-group leaf accounts):**

- Credit head: `Student Receivable Cybervidya - {ABBR}`
- Cash debit head: `Cash Cyber Vidhya - {ABBR}`
  - NOTE the deliberate spelling difference: cash head is **"Cyber Vidhya"** (two words,
    with an "h"); receivable head is **"Cybervidya"** (one word, no "h"). Do not
    "correct" or normalise either.

Rules:

- `{ABBR}` = the company's **actual `abbr` field** read from ERPNext (`Company.abbr`).
  Never hardcode or guess it.
- The credit (and cash debit) head is **derived** from the company; the **bank** ledger
  is **resolved from the mapping** (§5).
- Always **existence-check** the resolved/derived accounts: must exist, be non-group
  (`is_group = 0`); bank must be `account_type = "Bank"`. On any miss → **reject loudly**;
  never fall back to a default account.
- **Auto-submit** the JE on creation (posts to ledger immediately).
- `posting_date` = the payload `collection_date`.
- Receivable head is classified under Current Liabilities and cleared to income by a
  year-end JE — that year-end JE is OUT of scope for this app.
  - **Open question (flagged 2026-05-25):** in `GHR CACS Pune` (abbr `CACSPU`) the
    receivable head is actually under **Current Assets** (`root_type=Asset`, parent
    `Current Assets - CACSPU`), not Current Liabilities. The app behaves the same
    either way, but the year-end JE logic may need to know which side this lives on.
    Worth a sweep of all 59 companies before go-live.

---

## 4. Custom field on Journal Entry (idempotency key)

Add via `fixtures/custom_field.json` (exported fixture, version-controlled):

- DocType: **Journal Entry**
- Fieldname: **`custom_cybervidya_ref`**, type **Data**, **`unique = 1`**, read-only in UI.

The `unique = 1` gives a **database-level** uniqueness constraint — this is the hard
backstop that makes a double-post physically impossible (see §7).

---

## 5. DocTypes

### `CyberVidya Account Mapping` (parent — one record per institution)

| Field | Type | Notes |
|---|---|---|
| `cybervidya_institution` | Data | Reqd, **unique**. CyberVidya's institution code (the payload `institution` value). |
| `company` | Link → Company | Reqd. |
| `bank_accounts` | Table → `CyberVidya Bank Map` | Bank rows for this institution. |

### `CyberVidya Bank Map` (child table)

| Field | Type | Notes |
|---|---|---|
| `cybervidya_bank` | Data | Reqd. CyberVidya's bank code (the payload `bank` value). |
| `bank_account` | Link → Account | Reqd. The non-group, Bank-type leaf ledger in the parent's company. |

**`validate` hook on the parent (catch bad mappings at save time, not at 11pm):**

- `company` is set and valid.
- Each `bank_account`: `is_group = 0`, `account_type = "Bank"`, and `company` matches the
  parent's `company`.
- `cybervidya_bank` unique within the parent.

Cash needs **no** mapping row — the cash head is derived from the company.

This DocType is the destination for the CyberVidya mapping worksheet: parent rows =
(their institution code ↔ our company); bank child rows = (their bank code ↔ our ledger).

---

## 6. Endpoint

- Whitelisted method: **`dux_cybervidya.api.collection.post_daily_collection`**
  (confirm final path; share it with CyberVidya with the credentials).
- Auth: a **dedicated integration user** (NOT System Manager) with a tightly-scoped
  custom role. API key + secret in header: `Authorization: token <key>:<secret>`. HTTPS only.

**Request payload:**

| Field | Type | Required | Meaning |
|---|---|---|---|
| `reference` | string | Yes | Stable, unique idempotency key per record. Same on retry; distinct otherwise (incl. cash vs bank same day). **Primary** dup key. |
| `institution` | string | Yes | CyberVidya institution code → resolve Company via mapping. |
| `collection_type` | string | Yes | `"bank"` or `"cash"`. |
| `bank` | string | Conditional | CyberVidya bank code. Required iff `collection_type = "bank"`. |
| `amount` | number | Yes | Total for this institution + channel + date. Must be > 0. |
| `collection_date` | string | Yes | `YYYY-MM-DD`. Becomes JE `posting_date`. |
| `remarks` | string | No | Optional note onto the JE. |

**Processing sequence (implement in order):**

1. Authenticate (integration user token).
2. Validate payload: required fields present; `collection_type` ∈ {bank, cash};
   `amount > 0`; `collection_date` valid; `bank` present iff type = bank.
3. **Idempotency check** — look up `custom_cybervidya_ref`. If a JE already has it →
   return `already_exists` with that JE name, **stop**.
4. Resolve `institution` → Company via `CyberVidya Account Mapping`. Miss → reject.
5. Resolve debit ledger:
   - `bank`: look up (institution, bank) → `bank_account` in that company; validate
     non-group, `account_type = "Bank"`, company matches. Miss → reject.
   - `cash`: build `Cash Cyber Vidhya - {ABBR}` from `Company.abbr`; verify non-group leaf. Miss → reject.
6. Build credit head `Student Receivable Cybervidya - {ABBR}` from `Company.abbr`; verify
   non-group leaf. Miss → reject.
7. Build JE: `company`, `posting_date = collection_date`, one debit line + one credit line
   for `amount`, set `custom_cybervidya_ref = reference`, `user_remark = remarks`.
8. Insert + submit (auto-submit). Let the DB unique constraint win any race; on
   duplicate-key error, fetch and return the existing JE as `already_exists`.
9. Return `created` with the JE name.
10. On any rejection or unhandled error → fire alert (§9) and return the structured rejection.

---

## 7. Idempotency

- **Primary:** `custom_cybervidya_ref` unique DB constraint. Read-then-create, but treat
  the **duplicate-key insert error** as authoritative — catch it, fetch the existing JE,
  return `already_exists`. This closes the read→write race window.
- **The idempotency check only counts ACTIVE (docstatus=1) JEs.** A cancelled JE has
  zero ledger impact, so a retry of the same reference must be allowed to create a
  fresh JE. To make this work with the unique DB constraint:
  - `Journal Entry.on_cancel` hook (`utils.on_journal_entry_cancel`) automatically
    suffixes the cancelled JE's `custom_cybervidya_ref` with `__CANCELLED__<JE-name>`.
    This releases the original reference for re-posting while preserving an audit link
    on the cancelled JE.
  - The endpoint also runs `utils.free_cancelled_ref_holder` before every insert as a
    safety net (handles JEs cancelled before the hook existed, or hook-failure cases).
  - Cancelled-then-suffixed JEs are still searchable for audit: a list-view filter
    on `custom_cybervidya_ref LIKE '<ref>%'` returns both the cancelled record and
    the new active record for that reference.
- **Secondary (derived server-side, needs nothing from CyberVidya):** natural key
  `company + collection_type + ledger + posting_date` — sanity check / reconciliation only.
- v16 immutable ledger: a submitted JE can only be cancelled+reversed, never edited — which
  is exactly why idempotency is mandatory under auto-submit.

---

## 8. Responses (nested under Frappe's `message` envelope)

```json
{ "message": { "status": "created",        "journal_entry": "ACC-JV-2026-00123", "reference": "<ref>" } }
{ "message": { "status": "already_exists", "journal_entry": "ACC-JV-2026-00123", "reference": "<ref>" } }
{ "message": { "status": "rejected",       "reference": "<ref>", "reason": "<human-readable reason>" } }
```

`already_exists` is a SUCCESS (so retries are safe), not an error.

---

## 9. Rejection handling & alerts

On any rejection or unhandled exception: return the structured `rejected` response AND
raise an alert the same night (Frappe Notification / email) so an end-of-day failure isn't
discovered next morning. **Recipients: TBD** (Aditya / Abhijeet — open item §12).

Configuration: site_config key `dux_cybervidya_alert_recipients` (comma-string or list
of emails). When unset, rejections only land in the Error Log.

---

## 10. Target app structure

```
dux_cybervidya/
  hooks.py                      # fixtures (custom_field), doc_events if needed
  api/
    __init__.py
    collection.py               # @frappe.whitelist() post_daily_collection
    utils.py                    # resolve company/ledger, build_je, existence checks, alerts
  dux_cybervidya/
    doctype/
      cybervidya_account_mapping/   # parent + validate controller
      cybervidya_bank_map/          # child table
  fixtures/
    custom_field.json           # Journal Entry.custom_cybervidya_ref (unique)
```

---

## 11. Out of scope (do not build here)

- Billing / demand entries (Dr Receivable / Cr Fee Income).
- Year-end income recognition JE.
- Student-level transactions / receivables (stay in CyberVidya).
- Reconciliation automation (a daily report filtering `custom_cybervidya_ref` may come
  later; not part of the core build).

---

## 12. Open items (pre-go-live)

1. **Mapping data** — populate `CyberVidya Account Mapping` from CyberVidya's returned
   worksheet (institution codes ↔ companies; bank codes ↔ bank leaf ledgers).
2. **Reference scheme** — confirm CyberVidya emits a stable-on-retry / distinct-otherwise
   reference, including distinct cash vs bank on the same day.
3. **Rejection alert recipients & channel** (Aditya / Abhijeet; email / in-app).
4. **Final endpoint path** + create the dedicated integration user with scoped role.
5. **Frappe Cloud install** — add app to the FC bench for `ghraisoni.frappe.cloud`
   (GitHub repo access for FC; mirror the dux_voucher / dux_portal deploy flow).
6. **Receivable head placement sweep** — see §3 open question; confirm across all 59
   companies whether `Student Receivable Cybervidya - {ABBR}` sits under Current
   Assets or Current Liabilities, and reconcile with the year-end JE expectation.

---

## 13. Test matrix (dev: erp.jewonline.in, sample payloads)

- Bank collection → `created`, correct Dr/Cr, correct company, `custom_cybervidya_ref` set.
- Cash collection → `created`, Dr `Cash Cyber Vidhya - {ABBR}`.
- Duplicate (same `reference`) → `already_exists`, no second JE.
- Retry after simulated timeout (JE created, response "lost") → `already_exists`.
- Rejections: unmapped institution; unmapped bank; missing/derived account absent;
  group account; `amount <= 0`; bad `collection_type`; `bank` missing on bank type.
- Same company, same day, two banks (distinct refs) → two JEs.
- Same company, same day, cash + bank (distinct refs) → two JEs.
