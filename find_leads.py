#!/usr/bin/env python3
"""
Local business lead generator.

Searches the Google Places API for businesses in a given category/location
(e.g. "car rental" agencies in "Austin, TX, USA"), pulls their name, phone,
website, address and rating via Text Search + Place Details, then makes a
best-effort attempt to find a contact email by crawling the business's own
homepage and contact/about page. Results are written to a CSV for manual
outreach.

This script only *collects* data — it does not send emails, texts, or any
other outbound message to the businesses it finds.

Usage:
    python find_leads.py --category "car rental" --city "Austin" --country "USA"
    python find_leads.py --category property_rental --city "Lisbon" --country "Portugal" --output lisbon_leads.csv

Run `python find_leads.py --help` for all options. See README.md for setup.
"""

import argparse
import csv
import os
import re
import sys
import time
from html import unescape
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Config — edit these defaults, or override via CLI flags (see --help).
# ---------------------------------------------------------------------------

DEFAULT_CATEGORY = "car rental"
DEFAULT_CITY = "Austin"
DEFAULT_COUNTRY = "USA"
DEFAULT_OUTPUT = "leads.csv"
DEFAULT_MAX_RESULTS = 20  # Each result costs one Place Details call — keep modest.

REQUEST_TIMEOUT = 10  # seconds, for website crawling requests
API_REQUEST_DELAY = 1.0  # seconds between Google API calls (rate limiting)
SITE_REQUEST_DELAY = 1.5  # seconds between requests made to a business's own website
NEXT_PAGE_TOKEN_DELAY = 2.5  # Google requires a short delay before a next_page_token activates
MAX_CONTACT_PAGES_TO_CRAWL = 2  # besides the homepage, how many contact/about links to try

# Friendly shortcuts for --category. Free-text categories work too.
CATEGORY_PRESETS = {
    "car_rental": "car rental",
    "property_rental": "vacation rental property management",
    "airbnb_rental": "Airbnb rental agency",
}

PLACES_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
PLACE_DETAILS_FIELDS = "name,formatted_phone_number,international_phone_number,website,formatted_address,rating"

CONTACT_PAGE_KEYWORDS = ("contact", "about")

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._%+-]*@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
MAILTO_REGEX = re.compile(r'href=["\']mailto:([^"\'?]+)', re.IGNORECASE)

# Emails matching these are dropped as false positives (tracking pixels,
# placeholder addresses, image filenames that happen to look like emails).
EMAIL_BLOCKLIST_DOMAINS = (
    "sentry.io",
    "wixpress.com",
    "example.com",
    "godaddy.com",
    "yourdomain.com",
    "domain.com",
    "email.com",
)
EMAIL_BLOCKLIST_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")

USER_AGENT = "Mozilla/5.0 (compatible; LeadGenBot/1.0; +local manual research tool)"

CSV_COLUMNS = ["business_name", "phone", "email", "website", "address", "rating"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Find local businesses via Google Places and export leads to CSV."
    )
    parser.add_argument(
        "--category",
        default=DEFAULT_CATEGORY,
        help=(
            "Business category to search for. Accepts a preset "
            f"({', '.join(CATEGORY_PRESETS)}) or free text, e.g. 'car rental'. "
            f"Default: {DEFAULT_CATEGORY!r}"
        ),
    )
    parser.add_argument("--city", default=DEFAULT_CITY, help=f"City to search in. Default: {DEFAULT_CITY!r}")
    parser.add_argument(
        "--country", default=DEFAULT_COUNTRY, help=f"Country to search in. Default: {DEFAULT_COUNTRY!r}"
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Google Places API key. Falls back to the GOOGLE_PLACES_API_KEY env var.",
    )
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT, help=f"CSV file to write. Default: {DEFAULT_OUTPUT!r}"
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=DEFAULT_MAX_RESULTS,
        help=f"Max number of businesses to fetch (Google caps Text Search at 60). Default: {DEFAULT_MAX_RESULTS}",
    )
    parser.add_argument(
        "--skip-email-crawl",
        action="store_true",
        help="Skip crawling business websites for emails (Places data only, faster).",
    )
    return parser.parse_args()


def build_query(category, city, country):
    location = ", ".join(part for part in (city, country) if part)
    return f"{category} in {location}" if location else category


def polite_sleep(seconds):
    if seconds > 0:
        time.sleep(seconds)


def request_json_with_retry(session, url, params, max_retries=3):
    """GET a JSON endpoint, retrying on transient Google API errors."""
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"  Warning: request failed ({exc}), attempt {attempt}/{max_retries}")
            polite_sleep(2 * attempt)
            continue

        status = data.get("status")
        if status == "OVER_QUERY_LIMIT" and attempt < max_retries:
            print("  Warning: hit OVER_QUERY_LIMIT, backing off...")
            polite_sleep(3 * attempt)
            continue
        return data

    return {"status": "ERROR", "results": []}


def search_places(session, query, api_key, max_results):
    """Google Places Text Search, paginated up to max_results (Google caps at 60)."""
    places = []
    params = {"query": query, "key": api_key}
    next_page_token = None

    while len(places) < max_results:
        if next_page_token:
            polite_sleep(NEXT_PAGE_TOKEN_DELAY)
            params = {"pagetoken": next_page_token, "key": api_key}

        data = request_json_with_retry(session, PLACES_TEXT_SEARCH_URL, params)
        status = data.get("status")

        if status == "ZERO_RESULTS":
            break
        if status not in ("OK",):
            print(f"  Places Text Search returned status={status!r}: {data.get('error_message', '')}")
            break

        for result in data.get("results", []):
            places.append(result)
            if len(places) >= max_results:
                break

        next_page_token = data.get("next_page_token")
        if not next_page_token:
            break

        polite_sleep(API_REQUEST_DELAY)

    return places[:max_results]


def get_place_details(session, place_id, api_key):
    params = {"place_id": place_id, "fields": PLACE_DETAILS_FIELDS, "key": api_key}
    polite_sleep(API_REQUEST_DELAY)
    data = request_json_with_retry(session, PLACES_DETAILS_URL, params)
    if data.get("status") != "OK":
        return {}
    return data.get("result", {})


def is_valid_email(email):
    email = email.lower().strip().strip(".,;:")
    if not EMAIL_REGEX.fullmatch(email):
        return False
    domain = email.split("@")[-1]
    if domain in EMAIL_BLOCKLIST_DOMAINS:
        return False
    if email.endswith(EMAIL_BLOCKLIST_EXTENSIONS):
        return False
    return True


def extract_emails_from_html(html):
    emails = set()

    for match in MAILTO_REGEX.finditer(html):
        candidate = unescape(match.group(1)).strip().split("?")[0]
        if is_valid_email(candidate):
            emails.add(candidate.lower())

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ")
    for match in EMAIL_REGEX.finditer(text):
        candidate = match.group(0)
        if is_valid_email(candidate):
            emails.add(candidate.lower())

    return emails, soup


def find_contact_page_links(soup, base_url):
    """Find same-domain links whose href/text look like a contact or about page."""
    base_domain = urlparse(base_url).netloc
    links = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue

        absolute = urljoin(base_url, href)
        if urlparse(absolute).netloc != base_domain:
            continue

        haystack = f"{href} {a.get_text(' ')}".lower()
        if any(keyword in haystack for keyword in CONTACT_PAGE_KEYWORDS):
            if absolute not in seen:
                seen.add(absolute)
                links.append(absolute)

    return links[:MAX_CONTACT_PAGES_TO_CRAWL]


def fetch_page(session, url):
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type and "html" not in content_type:
            return None
        return resp.text
    except requests.RequestException:
        return None


def crawl_site_for_email(session, website):
    """Best-effort: check the homepage, then a contact/about page, for an email."""
    if not website:
        return ""

    url = website if website.startswith(("http://", "https://")) else f"http://{website}"

    polite_sleep(SITE_REQUEST_DELAY)
    html = fetch_page(session, url)
    if not html:
        return ""

    emails, soup = extract_emails_from_html(html)
    if emails:
        return sorted(emails)[0]

    for link in find_contact_page_links(soup, url):
        polite_sleep(SITE_REQUEST_DELAY)
        sub_html = fetch_page(session, link)
        if not sub_html:
            continue
        sub_emails, _ = extract_emails_from_html(sub_html)
        if sub_emails:
            return sorted(sub_emails)[0]

    return ""


def build_row(details, email):
    phone = details.get("formatted_phone_number") or details.get("international_phone_number") or ""
    rating = details.get("rating")
    return {
        "business_name": details.get("name", ""),
        "phone": phone,
        "email": email,
        "website": details.get("website", ""),
        "address": details.get("formatted_address", ""),
        "rating": rating if rating is not None else "",
    }


def write_csv(rows, output_path):
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    args = parse_args()

    api_key = args.api_key or os.environ.get("GOOGLE_PLACES_API_KEY")
    if not api_key:
        sys.exit(
            "Error: no Google Places API key found. Pass --api-key or set GOOGLE_PLACES_API_KEY "
            "(see README.md for how to get one)."
        )

    category = CATEGORY_PRESETS.get(args.category, args.category)
    query = build_query(category, args.city, args.country)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    print(f"Searching Google Places for: {query!r}")
    places = search_places(session, query, api_key, args.max_results)
    print(f"Found {len(places)} candidate business(es). Fetching details...")

    rows = []
    for i, place in enumerate(places, 1):
        place_id = place.get("place_id")
        if not place_id:
            continue

        details = get_place_details(session, place_id, api_key)
        if not details:
            details = {"name": place.get("name", ""), "formatted_address": place.get("formatted_address", "")}

        name = details.get("name") or "(unknown)"
        website = details.get("website", "")

        email = ""
        if website and not args.skip_email_crawl:
            print(f"  [{i}/{len(places)}] {name}: crawling {website} for an email...")
            email = crawl_site_for_email(session, website)
        else:
            print(f"  [{i}/{len(places)}] {name}: no website to crawl")

        rows.append(build_row(details, email))

    write_csv(rows, args.output)
    print(f"\nWrote {len(rows)} lead(s) to {args.output}")


if __name__ == "__main__":
    main()
