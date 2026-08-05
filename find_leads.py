#!/usr/bin/env python3
"""Local business market research and lead qualification, worldwide.

Two modes:

    scan      one city, one category — the quick "who's in this town" pass
    research  many cities and categories from a YAML config, scored and
              ranked so you can see which market is worth entering at all

Both write CSVs for manual outreach. Nothing here sends messages.

    python find_leads.py scan --category car_rental --city Lisbon --country Portugal
    python find_leads.py research --config markets.yml --dry-run
    python find_leads.py research --config markets.yml --out-dir out/

Run `python find_leads.py <mode> --help` for the full flag list, and see
README.md for API key setup.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from leadgen.cache import Cache
from leadgen.config import ICP, Category, Market, ResearchConfig, load_config
from leadgen.enrich import SiteEnricher
from leadgen.export import write_leads, write_legacy_csv, write_markets, write_run_report
from leadgen.places import PlacesClient, PlacesError
from leadgen.research import rank_leads, rank_markets, research_market

CATEGORY_PRESETS = {
    "car_rental": "car rental agency",
    "property_rental": "vacation rental management company",
    "airbnb_rental": "short term rental agency",
    "boat_rental": "boat rental",
    "tour_operator": "tour operator",
}

DEFAULT_CACHE = ".leadgen-cache.json"


def add_common_flags(parser):
    parser.add_argument("--api-key", help="Google Places API key (else GOOGLE_PLACES_API_KEY).")
    parser.add_argument("--no-cache", action="store_true", help="Ignore the local API response cache.")
    parser.add_argument("--cache-file", default=DEFAULT_CACHE, help=f"Cache path. Default: {DEFAULT_CACHE}")
    parser.add_argument("--skip-email-crawl", action="store_true", help="Skip website crawling entirely (faster, cheaper, far less signal).")
    parser.add_argument("--ignore-robots", action="store_true", help="Crawl pages robots.txt disallows. Off by default — leave it off.")
    parser.add_argument("--site-delay", type=float, default=1.5, help="Seconds between requests to a business site. Default: 1.5")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Research local business markets worldwide and export qualified leads.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="mode")

    scan = sub.add_parser("scan", help="Scan a single city for one category.")
    scan.add_argument("--category", default="car_rental", help=f"Preset ({', '.join(CATEGORY_PRESETS)}) or free text.")
    scan.add_argument("--city", default="Austin")
    scan.add_argument("--country", default="USA")
    scan.add_argument("--language", default="", help="ISO 639-1 code for localized results, e.g. 'pt'.")
    scan.add_argument("--region", default="", help="ccTLD to bias results toward, e.g. 'pt'.")
    scan.add_argument("--max-results", type=int, default=20, help="Businesses to fetch. Google caps one query at 60. Default: 20")
    scan.add_argument("--output", default="leads.csv")
    scan.add_argument("--legacy-columns", action="store_true", help="Write the original 6-column CSV instead of the scored sheet.")
    add_common_flags(scan)

    research = sub.add_parser("research", help="Scan many markets from a config and rank them.")
    research.add_argument("--config", default="markets.yml")
    research.add_argument("--out-dir", default="out")
    research.add_argument("--max-per-market", type=int, help="Override max_per_market from the config.")
    research.add_argument("--dry-run", action="store_true", help="Show the plan and estimated API calls without spending anything.")
    add_common_flags(research)

    # Keep the original flag-only invocation working: `find_leads.py --city X`.
    if argv and argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        argv = ["scan"] + argv
    args = parser.parse_args(argv)
    if not args.mode:
        parser.print_help()
        sys.exit(0)
    return args


def resolve_api_key(args):
    key = args.api_key or os.environ.get("GOOGLE_PLACES_API_KEY")
    if not key:
        sys.exit(
            "Error: no Google Places API key found. Pass --api-key or set "
            "GOOGLE_PLACES_API_KEY (see README.md for how to get one)."
        )
    return key


def build_clients(args, api_key):
    cache = Cache(args.cache_file, enabled=not args.no_cache)
    session = requests.Session()
    client = PlacesClient(api_key, session=session, cache=cache)
    enricher = SiteEnricher(
        delay=args.site_delay,
        respect_robots=not args.ignore_robots,
        cache=cache,
    )
    return client, enricher, cache


def cmd_scan(args):
    api_key = resolve_api_key(args)
    client, enricher, cache = build_clients(args, api_key)

    query = CATEGORY_PRESETS.get(args.category, args.category)
    category = Category(id=args.category, query=query)
    market = Market(city=args.city, country=args.country, language=args.language, region=args.region)
    config = ResearchConfig(
        icp=ICP(),
        categories=[category],
        markets=[market],
        max_per_market=args.max_results,
        crawl_websites=not args.skip_email_crawl,
    )

    print(f"Scanning {market.id} for {category.label!r}...")

    def progress(index, total, lead):
        flag = f"[{lead.tier}]" if lead.tier != "-" else "[ ]"
        print(f"  {flag} {index}/{total} {lead.business_name or '(unnamed)'} — score {lead.fit_score}")

    try:
        leads, summary = research_market(client, enricher, market, category, config, progress)
    except PlacesError as exc:
        cache.save()
        sys.exit(f"Error: {exc}\nSee README.md for API key setup.")

    leads = rank_leads(leads)
    if args.legacy_columns:
        write_legacy_csv(leads, args.output)
    else:
        write_leads(leads, args.output)
    cache.save()

    print(f"\nWrote {len(leads)} lead(s) to {args.output}")
    report_totals(leads, summary, client, cache)
    return 0


def report_totals(leads, summary, client, cache):
    with_email = sum(1 for lead in leads if lead.email)
    tier_a = sum(1 for lead in leads if lead.tier == "A")
    whatsapp = sum(1 for lead in leads if lead.whatsapp)
    print(
        f"  {tier_a} tier-A · {with_email} with email · {whatsapp} with a WhatsApp number "
        f"· opportunity score {summary.opportunity_score}/100"
    )
    print(
        f"  API calls: {client.search_calls} search + {client.details_calls} details "
        f"(cache hits: {cache.hits})"
    )


def plan_summary(config):
    lines = []
    for market in config.markets:
        for category in config.categories:
            lines.append(f"  {market.id:<34} {category.label:<32} {len(market.queries(category))} query(ies)")
    return lines


def cmd_research(args):
    try:
        config = load_config(args.config)
    except ValueError as exc:
        sys.exit(f"Error: {exc}")

    if args.max_per_market:
        config.max_per_market = args.max_per_market
    if args.skip_email_crawl:
        config.crawl_websites = False

    pairs = len(config.markets) * len(config.categories)
    searches = config.planned_queries
    max_details = pairs * config.max_per_market

    print(f"ICP: {config.icp.name}")
    print(f"Plan: {len(config.markets)} market(s) x {len(config.categories)} category(ies) = {pairs} scans")
    for line in plan_summary(config):
        print(line)
    print(
        f"\nEstimated API calls: ~{searches} Text Search (plus pagination) "
        f"and up to {max_details} Place Details."
    )
    print(
        "Place Details is the expensive half and is billed per call and per field tier. "
        "Check current rates at https://developers.google.com/maps/billing-and-pricing "
        "and start with a small --max-per-market."
    )

    if args.dry_run:
        print("\nDry run — nothing was requested and nothing was billed.")
        return 0

    api_key = resolve_api_key(args)
    client, enricher, cache = build_clients(args, api_key)

    all_leads, summaries = [], []
    started = time.time()

    for market in config.markets:
        for category in config.categories:
            print(f"\n=== {market.id} · {category.label} ===")
            try:
                leads, summary = research_market(client, enricher, market, category, config)
            except PlacesError as exc:
                cache.save()
                sys.exit(f"Error: {exc}\nSee README.md for API key setup.")

            all_leads.extend(leads)
            summaries.append(summary)
            print(
                f"  {summary.businesses_found} found · {summary.qualified} qualified · "
                f"{summary.tier_a} tier-A · {summary.contactability_pct}% contactable · "
                f"{summary.whatsapp_pct}% on WhatsApp · opportunity {summary.opportunity_score}/100"
            )
            cache.save()

    ranked_leads = rank_leads(all_leads)
    ranked_markets = rank_markets(summaries)

    leads_path = os.path.join(args.out_dir, "leads.csv")
    markets_path = os.path.join(args.out_dir, "markets.csv")
    report_path = os.path.join(args.out_dir, "run.json")

    write_leads(ranked_leads, leads_path)
    write_markets(ranked_markets, markets_path)
    write_run_report(report_path, {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "icp": config.icp.name,
        "weights": config.icp.weights,
        "markets": len(config.markets),
        "categories": [c.label for c in config.categories],
        "leads": len(ranked_leads),
        "tier_a": sum(1 for l in ranked_leads if l.tier == "A"),
        "api_calls": {"text_search": client.search_calls, "place_details": client.details_calls},
        "cache": {"hits": cache.hits, "misses": cache.misses},
        "duration_seconds": round(time.time() - started, 1),
    })
    cache.save()

    print("\n" + "=" * 66)
    print(f"{len(ranked_leads)} leads across {len(summaries)} market scans")
    print(f"  {leads_path}   — every lead, best fit first")
    print(f"  {markets_path} — markets ranked by opportunity")
    print(f"  {report_path}  — run metadata and API usage")

    print("\nTop markets by opportunity:")
    for summary in ranked_markets[:5]:
        print(
            f"  {summary.opportunity_score:>3}/100  {summary.market:<32} "
            f"{summary.qualified:>3} qualified  {summary.whatsapp_pct:>5}% WhatsApp"
        )

    print("\nTop leads:")
    for lead in ranked_leads[:5]:
        contact = lead.whatsapp or lead.email or lead.phone_e164 or lead.phone or "no contact"
        print(f"  [{lead.tier}] {lead.fit_score:>3}  {lead.business_name[:34]:<34} {contact}")

    print(
        f"\nAPI calls: {client.search_calls} search + {client.details_calls} details "
        f"(cache hits: {cache.hits})"
    )
    return 0


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.mode == "research":
        return cmd_research(args)
    return cmd_scan(args)


if __name__ == "__main__":
    sys.exit(main())
