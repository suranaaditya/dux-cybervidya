app_name = "dux_cybervidya"
app_title = "Dux CyberVidya"
app_publisher = "Dux DigiTech"
app_description = "ERPNext receiver for CyberVidya end-of-day fee collection: one aggregated, auto-submitted Journal Entry per (company, channel, date)."
app_email = "aditya@duxdigitech.com"
app_license = "MIT"

fixtures = [
    {
        "doctype": "Custom Field",
        "filters": [
            ["name", "in", ["Journal Entry-custom_cybervidya_ref"]],
        ],
    },
    {
        "doctype": "Role",
        "filters": [
            ["name", "in", ["CyberVidya Viewer"]],
        ],
    },
    # Read-only Journal Entry access for the CyberVidya Viewer role so the
    # dashboard endpoints (guarded on Journal Entry read) work for that role.
    {
        "doctype": "Custom DocPerm",
        "filters": [
            ["role", "in", ["CyberVidya Viewer"]],
        ],
    },
]

# When a CyberVidya-posted JE is cancelled (in the UI or programmatically),
# free its idempotency reference so CyberVidya can retry. See utils.py.
doc_events = {
    "Journal Entry": {
        "on_cancel": "dux_cybervidya.api.utils.on_journal_entry_cancel",
    },
}

# Refresh the dashboard's institution<->company<->abbr cache after migrate
# (mappings may have changed).
after_migrate = [
    "dux_cybervidya.api.dashboard.refresh_maps",
    "dux_cybervidya.api.other_fees_dashboard.refresh_other_fees_maps",
]
