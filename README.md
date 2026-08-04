# Lead Generation Tool

A standalone Python script that finds local businesses in a category/city
(starting with **car rental** and **property/Airbnb rental agencies**) and
exports them to a CSV you can use for manual outreach — e.g. as a source of
leads for pitching a product to rental/Airbnb hosts.

For each business it pulls:

- Name, phone, website, address, and rating — from the Google Places API
  (Text Search + Place Details)
- Email — best-effort, by crawling the business's own homepage and a
  contact/about page for `mailto:` links or an email-shaped string. When a
  site lists several addresses, the one most useful for outreach wins
  (`reservations@`/`info@` over `press@`/`careers@`/`noreply@`).

It writes one row per business to a CSV with columns:
`business_name, phone, email, website, address, rating`. Missing fields are
left blank instead of crashing the script.

**This tool only collects data.** It does not send emails, texts, or any
other message to the businesses it finds — outreach is on you, manually.

## 1. Get a Google Places API key

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and
   create a project (or pick an existing one).
2. Enable the **Places API** for that project: APIs & Services → Library →
   search "Places API" → Enable.
3. Create credentials: APIs & Services → Credentials → Create Credentials →
   API key.
4. (Recommended) Restrict the key to the Places API and, if possible, to
   your IP, so it can't be reused elsewhere if leaked.
5. Billing must be enabled on the project — Google gives Places API a
   monthly free credit, but Text Search and Place Details calls are billed
   beyond that. Check current pricing at
   https://developers.google.com/maps/billing-and-pricing before running
   large searches.

## 2. Install dependencies

Requires **Python 3.9+**.

```bash
git clone https://github.com/anjuneedham/lead-gen-tool
cd lead-gen-tool
python3 -m venv venv && source venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

## 3. Set your API key

Either export it as an environment variable:

```bash
export GOOGLE_PLACES_API_KEY="your-key-here"
```

or create a `.env` file in this directory (gitignored) with:

```
GOOGLE_PLACES_API_KEY=your-key-here
```

or pass it directly with `--api-key` on every run.

## 4. Run it

```bash
python find_leads.py --category "car rental" --city "Austin" --country "USA"
```

```bash
python find_leads.py --category property_rental --city "Lisbon" --country "Portugal" --output lisbon_leads.csv
```

### Options

| Flag | Description | Default |
|---|---|---|
| `--category` | Preset (`car_rental`, `property_rental`, `airbnb_rental`) or free text, e.g. `"vacation rental company"` | `car rental` |
| `--city` | City to search in | `Austin` |
| `--country` | Country to search in | `USA` |
| `--api-key` | Google Places API key (overrides env var) | — |
| `--output` | CSV file path to write | `leads.csv` |
| `--max-results` | Max businesses to fetch (Google Text Search caps at 60 per query) | `20` |
| `--skip-email-crawl` | Skip website crawling, just export Places data | off |

Defaults can also be edited directly at the top of `find_leads.py` if you'd
rather not pass flags every time.

## Notes on rate limiting & cost

- Each business costs one Places **Text Search** result and one **Place
  Details** call — the script pauses briefly between API calls and paginated
  search requests to stay well under Google's rate limits.
- Website crawling is capped at the homepage plus up to 2 contact/about
  pages per business, with a delay between each request, so it doesn't
  hammer any single site.
- `--max-results` directly controls your Google Places bill — start small
  (10–20) to sanity-check results before scaling up.

## Troubleshooting

**`REQUEST_DENIED`** — the most common first-run error. It means one of:
the key is wrong, the **Places API** isn't enabled on the project, billing
isn't enabled, or a key restriction (IP/referrer) is blocking the call.
Work through step 1 above again.

**`OVER_QUERY_LIMIT`** — out of quota, or billing isn't enabled. The script
retries with backoff before giving up.

**Ran fine but most emails are blank** — expected. Many small businesses
publish only a contact form or put their address in an image. Phone numbers
are the more reliable channel for these leads; consider `--skip-email-crawl`
for a much faster run when you only need phone/address.

The script exits with a non-zero status on setup errors, so you can chain it
in a shell script safely.

## Limitations

- Email extraction is best-effort: many sites hide contact emails behind
  forms, JS-rendered content, or third-party spam-protection — those won't
  be found by a plain HTML crawl.
- Only the business's own homepage + contact/about page are crawled; the
  script does not search the wider web for an email.
- Google Places' category matching is fuzzy (it's a text search), so review
  results for relevance, especially for less common categories.
