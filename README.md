# Dux CyberVidya

ERPNext v16 receiver for CyberVidya end-of-day fee-collection data.

For each collection record, this app posts **one aggregated, auto-submitted Journal Entry** keyed by `(company, channel, date)`. CyberVidya sends a thin payload via a single whitelisted endpoint; all account resolution happens server-side using the `CyberVidya Account Mapping` DocType plus `Company.abbr`-derived heads.

See `CLAUDE.md` at the repo root for the locked design.

## Install (dev)

```bash
cd ~/frappe-bench
bench get-app dux_cybervidya https://github.com/suranaaditya/dux_cybervidya
bench --site erp.jewonline.in install-app dux_cybervidya
bench --site erp.jewonline.in migrate
bench --site erp.jewonline.in clear-cache
```
