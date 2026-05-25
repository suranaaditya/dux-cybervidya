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
]
