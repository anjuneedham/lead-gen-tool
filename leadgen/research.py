"""Orchestration: run categories across markets, score, and summarize."""

from .enrich import Enrichment
from .places import country_code
from .scoring import Lead, assign_tier, looks_like_chain, score_lead, summarize_market

try:
    import phonenumbers
except ImportError:  # pragma: no cover - optional, declared in requirements
    phonenumbers = None


def to_e164(raw_phone, iso_country):
    """Normalize a phone number to +<country><number>.

    Worth the dependency: a worldwide list has numbers in a dozen local
    formats, and anything you'd do with them later — WhatsApp, a dialer, a
    CRM import — needs E.164.
    """
    if not raw_phone or phonenumbers is None:
        return ""
    try:
        parsed = phonenumbers.parse(raw_phone, iso_country or None)
        if not phonenumbers.is_valid_number(parsed):
            return ""
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return ""


def build_lead(details, place, market, category, enrichment):
    """Fold a Places record plus website signals into one Lead row."""
    name = details.get("name") or place.get("name", "")
    phone = details.get("formatted_phone_number") or details.get("international_phone_number") or ""
    iso = country_code(details)

    lead = Lead(
        business_name=name,
        category=category.label,
        market=market.id,
        city=market.city,
        country=market.country,
        phone=phone,
        phone_e164=to_e164(details.get("international_phone_number") or phone, iso),
        whatsapp=enrichment.whatsapp_number,
        email=enrichment.email,
        website=details.get("website", ""),
        address=details.get("formatted_address") or place.get("formatted_address", ""),
        rating=details.get("rating", ""),
        review_count=details.get("user_ratings_total", ""),
        business_status=details.get("business_status", ""),
        maps_url=details.get("url", ""),
        place_id=place.get("place_id", ""),
        instagram=enrichment.socials.get("instagram", ""),
        facebook=enrichment.socials.get("facebook", ""),
        booking_platforms=", ".join(enrichment.booking_platforms),
        has_contact_form=enrichment.has_contact_form,
        is_chain=looks_like_chain(name),
    )
    return lead


def research_market(client, enricher, market, category, config, on_progress=None):
    """Search one market for one category, enrich and score every result."""
    seen, places = set(), []
    for query in market.queries(category):
        remaining = config.max_per_market - len(places)
        if remaining <= 0:
            break
        for place in client.text_search(
            query, language=market.language, region=market.region, max_results=remaining
        ):
            pid = place.get("place_id")
            if pid and pid not in seen:
                seen.add(pid)
                places.append(place)

    leads = []
    for index, place in enumerate(places, 1):
        pid = place.get("place_id")
        if not pid:
            continue
        details = client.details(pid, language=market.language) or {}
        if not details:
            details = {
                "name": place.get("name", ""),
                "formatted_address": place.get("formatted_address", ""),
            }

        name = details.get("name", "")
        if not name and not details.get("formatted_address"):
            continue

        website = details.get("website", "")
        enrichment = Enrichment()
        if website and config.crawl_websites:
            enrichment = enricher.enrich(website)

        lead = build_lead(details, place, market, category, enrichment)
        score, reasons, excluded = score_lead(lead, enrichment, config.icp)
        lead.fit_score = score
        lead.score_reasons = reasons
        lead.excluded_reason = excluded
        lead.tier = assign_tier(score, config.icp.tiers) if not excluded else "-"
        leads.append(lead)

        if on_progress:
            on_progress(index, len(places), lead)

    return leads, summarize_market(market, category, leads)


def rank_markets(summaries):
    return sorted(summaries, key=lambda s: s.opportunity_score, reverse=True)


def rank_leads(leads):
    return sorted(leads, key=lambda l: (l.fit_score, l.review_count or 0), reverse=True)
