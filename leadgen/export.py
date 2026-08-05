"""Writing results out: CSVs for working in, JSON for piping onward."""

import csv
import json
import os
from dataclasses import asdict

# Ordered for a human reading the sheet left to right: who they are, how to
# reach them, then why the tool ranked them where it did.
LEAD_COLUMNS = [
    "fit_score", "tier", "business_name", "category", "market", "country",
    "phone_e164", "phone", "whatsapp", "email", "website", "address",
    "rating", "review_count", "instagram", "facebook", "booking_platforms",
    "has_contact_form", "is_chain", "business_status", "maps_url",
    "score_reasons", "excluded_reason", "place_id",
]

MARKET_COLUMNS = [
    "opportunity_score", "market", "country", "category", "businesses_found",
    "qualified", "tier_a", "contactability_pct", "whatsapp_pct",
    "independent_pct", "avg_rating", "median_reviews", "with_phone",
    "with_email", "with_website", "using_whatsapp", "on_booking_platform",
    "notes",
]


def _ensure_parent(path):
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def _write(path, columns, rows):
    _ensure_parent(path)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _clean(value) for key, value in row.items()})
    return path


def _clean(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else ""
    return value


def write_leads(leads, path):
    """Write the lead sheet. utf-8-sig so Excel opens non-Latin names correctly."""
    return _write(path, LEAD_COLUMNS, [asdict(lead) for lead in leads])


def write_markets(summaries, path):
    return _write(path, MARKET_COLUMNS, [asdict(s) for s in summaries])


def write_run_report(path, report):
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    return path


def legacy_columns():
    """The original six-column format, for anything already parsing that CSV."""
    return ["business_name", "phone", "email", "website", "address", "rating"]


def write_legacy_csv(leads, path):
    rows = [
        {
            "business_name": lead.business_name,
            "phone": lead.phone,
            "email": lead.email,
            "website": lead.website,
            "address": lead.address,
            "rating": lead.rating,
        }
        for lead in leads
    ]
    return _write(path, legacy_columns(), rows)
