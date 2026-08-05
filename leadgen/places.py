"""Google Places client, set up for worldwide use.

Two things make this work outside one country: `language` returns results in
the local language rather than transliterated English, and `region` biases
ranking toward that country so "car rental in Córdoba" resolves to Argentina
rather than Spain when you say so.
"""

import time

import requests

TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# Requested Place Details fields. Google bills these in tiers: Basic (name,
# address, business_status, url) is cheapest, Contact (phone, website) and
# Atmosphere (rating, user_ratings_total) each cost more. We take all three
# because review count and reachability are the whole point of the research —
# drop `rating`/`user_ratings_total` here if you want a cheaper run.
DETAIL_FIELDS = ",".join([
    "name",
    "formatted_phone_number",
    "international_phone_number",
    "website",
    "formatted_address",
    "rating",
    "user_ratings_total",
    "business_status",
    "types",
    "url",
    "address_components",
])

# Statuses that mean the setup is wrong rather than "nothing matched".
FATAL_STATUSES = {
    "REQUEST_DENIED": "Check the key is correct, the Places API is enabled, and key restrictions allow this request.",
    "INVALID_REQUEST": "The request was malformed — check the category and city values.",
    "OVER_QUERY_LIMIT": "The key is out of quota, or billing is not enabled on the project.",
    "UNREACHABLE": "Could not reach the Google Places API — check your network connection.",
}

API_DELAY = 1.0
NEXT_PAGE_DELAY = 2.5
TIMEOUT = 15


class PlacesError(Exception):
    """Raised for setup problems worth stopping the whole run over."""


class PlacesClient:
    def __init__(self, api_key, session=None, cache=None, sleep=time.sleep):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.cache = cache
        self.sleep = sleep
        self.search_calls = 0
        self.details_calls = 0

    def _get(self, url, params, max_retries=3):
        for attempt in range(1, max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=TIMEOUT)
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                if attempt == max_retries:
                    return {"status": "UNREACHABLE", "error_message": str(exc)}
                self.sleep(2 * attempt)
                continue

            if payload.get("status") == "OVER_QUERY_LIMIT" and attempt < max_retries:
                self.sleep(3 * attempt)
                continue
            return payload
        return {"status": "UNREACHABLE", "error_message": "retries exhausted"}

    def text_search(self, query, language="", region="", max_results=60):
        """Paginated Text Search. Returns raw place dicts (Google caps this at 60)."""
        results = []
        params = {"query": query, "key": self.api_key}
        if language:
            params["language"] = language
        if region:
            params["region"] = region

        token = None
        while len(results) < max_results:
            if token:
                # A fresh next_page_token isn't valid immediately.
                self.sleep(NEXT_PAGE_DELAY)
                params = {"pagetoken": token, "key": self.api_key}

            cache_key = f"search:{params.get('query', params.get('pagetoken'))}:{language}:{region}"
            payload = self.cache.get(cache_key) if self.cache else None
            if payload is None:
                payload = self._get(TEXT_SEARCH_URL, params)
                self.search_calls += 1
                if payload.get("status") in ("OK", "ZERO_RESULTS") and self.cache:
                    self.cache.set(cache_key, payload)

            status = payload.get("status")
            if status == "ZERO_RESULTS":
                break
            if status in FATAL_STATUSES and not results:
                detail = payload.get("error_message") or FATAL_STATUSES[status]
                raise PlacesError(f"Google Places returned {status}: {detail}")
            if status != "OK":
                break

            for item in payload.get("results", []):
                results.append(item)
                if len(results) >= max_results:
                    break

            token = payload.get("next_page_token")
            if not token:
                break
            self.sleep(API_DELAY)

        return results[:max_results]

    def details(self, place_id, language=""):
        """Place Details for one place_id. Returns {} when the lookup fails."""
        cache_key = f"details:{place_id}:{language}"
        cached = self.cache.get(cache_key) if self.cache else None
        if cached is not None:
            return cached

        params = {"place_id": place_id, "fields": DETAIL_FIELDS, "key": self.api_key}
        if language:
            params["language"] = language

        self.sleep(API_DELAY)
        payload = self._get(DETAILS_URL, params)
        self.details_calls += 1
        if payload.get("status") != "OK":
            return {}

        result = payload.get("result", {})
        if self.cache:
            self.cache.set(cache_key, result)
        return result


def country_code(details):
    """Pull the ISO country code out of a details payload, for phone formatting."""
    for component in details.get("address_components") or []:
        if "country" in (component.get("types") or []):
            return (component.get("short_name") or "").upper()
    return ""
