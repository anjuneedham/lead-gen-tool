"""Lead scoring and market opportunity scoring.

Scoring is deliberately transparent: every lead carries the list of reasons
that produced its number, so you can argue with the model and retune the
weights instead of trusting a black box.
"""

from dataclasses import dataclass

# Global operators. A franchise of one of these does not buy software from a
# small vendor — the decision sits at head office, in another country.
CHAIN_BRANDS = {
    # Car rental
    "hertz", "avis", "enterprise rent", "europcar", "sixt", "budget rent",
    "alamo rent", "national car rental", "thrifty", "dollar rent", "goldcar",
    "firefly car", "green motion", "fox rent", "payless car", "ace rent",
    "zipcar", "localiza", "movida", "unidas", "addcar", "interrent",
    "keddy", "surprice car", "rentalcars",
    # Accommodation / property management
    "airbnb", "booking.com", "vrbo", "sonder", "vacasa", "interhome",
    "novasol", "wyndham", "marriott", "hilton", "accor", "oyo", "selina",
    "awaze", "evolve vacation", "turnkey", "hostelworld", "expedia",
    "radisson", "ibis", "novotel", "mercure", "holiday inn", "best western",
}


@dataclass
class Lead:
    """One business, with everything known about it and why it scored as it did."""

    business_name: str = ""
    category: str = ""
    market: str = ""
    city: str = ""
    country: str = ""
    phone: str = ""
    phone_e164: str = ""
    whatsapp: str = ""
    email: str = ""
    website: str = ""
    address: str = ""
    rating: object = ""
    review_count: object = ""
    business_status: str = ""
    maps_url: str = ""
    place_id: str = ""
    instagram: str = ""
    facebook: str = ""
    booking_platforms: str = ""
    has_contact_form: bool = False
    is_chain: bool = False
    fit_score: int = 0
    tier: str = ""
    score_reasons: str = ""
    excluded_reason: str = ""


def looks_like_chain(name):
    lowered = (name or "").lower()
    return any(brand in lowered for brand in CHAIN_BRANDS)


def _as_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def score_lead(lead, enrichment, icp):
    """Return (0-100 score, reasons, excluded_reason).

    An excluded_reason means the lead failed a hard filter — it's kept in the
    output (you may disagree with the filter) but flagged and scored 0.
    """
    reasons = []
    weights = icp.weights

    if icp.exclude_permanently_closed and lead.business_status == "CLOSED_PERMANENTLY":
        return 0, "permanently closed", "closed_permanently"
    if icp.exclude_chains and lead.is_chain:
        return 0, "global chain — buying decision is not local", "chain"

    rating = _as_number(lead.rating)
    if rating is not None and rating < icp.min_rating:
        return 0, f"rating {rating} below minimum {icp.min_rating}", "low_rating"

    raw = 0

    if enrichment.uses_whatsapp:
        raw += weights.get("uses_whatsapp", 0)
        reasons.append("already uses WhatsApp")

    if not lead.is_chain:
        raw += weights.get("independent", 0)
        reasons.append("independent operator")

    if lead.email:
        raw += weights.get("reachable_email", 0)
        reasons.append("email found")

    reviews = _as_number(lead.review_count)
    low, high = icp.review_count_range
    if reviews is not None and low <= reviews <= high:
        raw += weights.get("right_size", 0)
        reasons.append(f"{int(reviews)} reviews — in target size range")
    elif reviews is not None and reviews > high:
        reasons.append(f"{int(reviews)} reviews — larger than target")

    if rating is not None and rating >= 4.0:
        raw += weights.get("good_rating", 0)
        reasons.append(f"rated {rating}")

    if lead.phone:
        raw += weights.get("has_phone", 0)
        reasons.append("phone listed")

    if lead.website:
        raw += weights.get("has_website", 0)
    else:
        raw += weights.get("no_web_presence", 0)
        reasons.append("no website")

    # Contact-form-only means enquiries already pile up somewhere awkward.
    if enrichment.has_contact_form and not lead.email:
        raw += weights.get("contact_form_only", 0)
        reasons.append("contact form only — hard to reach")

    if enrichment.booking_platforms:
        raw += weights.get("has_booking_engine", 0)
        reasons.append("already on " + ", ".join(enrichment.booking_platforms[:2]))

    score = max(0, min(100, round(100 * raw / icp.max_positive_score)))
    return score, "; ".join(reasons), ""


def assign_tier(score, tiers):
    for name in sorted(tiers, key=lambda t: tiers[t], reverse=True):
        if score >= tiers[name]:
            return name
    return "C"


@dataclass
class MarketSummary:
    """How attractive a market is, and the evidence behind that judgement."""

    market: str = ""
    city: str = ""
    country: str = ""
    category: str = ""
    businesses_found: int = 0
    qualified: int = 0
    tier_a: int = 0
    independents: int = 0
    with_phone: int = 0
    with_email: int = 0
    with_website: int = 0
    using_whatsapp: int = 0
    on_booking_platform: int = 0
    avg_rating: object = ""
    median_reviews: object = ""
    contactability_pct: float = 0.0
    whatsapp_pct: float = 0.0
    independent_pct: float = 0.0
    opportunity_score: int = 0
    notes: str = ""


def _pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def _median(values):
    if not values:
        return ""
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return round((ordered[mid - 1] + ordered[mid]) / 2, 1)


def summarize_market(market, category, leads, qualify_at=45):
    """Aggregate scored leads into a market-level verdict.

    opportunity_score blends four things a seller actually cares about: how
    many good leads exist (density), whether you can reach them
    (contactability), whether they already live on the channel you sell
    (whatsapp), and whether the decision is local (independence).
    """
    summary = MarketSummary(
        market=market.id,
        city=market.city,
        country=market.country,
        category=category.label,
        businesses_found=len(leads),
        notes=market.notes,
    )
    if not leads:
        return summary

    ratings, reviews = [], []
    for lead in leads:
        if lead.excluded_reason:
            continue
        if lead.fit_score >= qualify_at:
            summary.qualified += 1
        if lead.tier == "A":
            summary.tier_a += 1

    for lead in leads:
        if not lead.is_chain:
            summary.independents += 1
        if lead.phone:
            summary.with_phone += 1
        if lead.email:
            summary.with_email += 1
        if lead.website:
            summary.with_website += 1
        if lead.whatsapp or "whatsapp" in (lead.score_reasons or ""):
            summary.using_whatsapp += 1
        if lead.booking_platforms:
            summary.on_booking_platform += 1
        rating = _as_number(lead.rating)
        if rating is not None:
            ratings.append(rating)
        count = _as_number(lead.review_count)
        if count is not None:
            reviews.append(count)

    total = len(leads)
    summary.avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else ""
    summary.median_reviews = _median(reviews)
    reachable = sum(1 for lead in leads if lead.email or lead.phone)
    summary.contactability_pct = _pct(reachable, total)
    summary.whatsapp_pct = _pct(summary.using_whatsapp, total)
    summary.independent_pct = _pct(summary.independents, total)

    # Density saturates at 25 qualified leads — beyond that a market is
    # "plenty to work with" and the other factors decide.
    density = min(1.0, summary.qualified / 25.0)
    summary.opportunity_score = round(
        100 * (
            0.40 * density
            + 0.25 * (summary.contactability_pct / 100)
            + 0.20 * (summary.whatsapp_pct / 100)
            + 0.15 * (summary.independent_pct / 100)
        )
    )
    return summary
