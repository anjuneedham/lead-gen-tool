# Local Market Research & Lead Generation Tool

Finds local businesses anywhere in the world via the Google Places API,
enriches them from their own websites, scores them against an ideal-customer
profile you define, and ranks both the **leads** and the **markets** they're
in.

Built originally for rental operators (car hire, vacation/Airbnb property
management), but the category and scoring model are config, not code.

**It only collects and ranks publicly published business information. It
never sends a message on any channel** — outreach stays manual. See
[WORKFLOWS.md](WORKFLOWS.md) for the processes this is designed to feed.

## Why market-level output

A list of businesses is a commodity. What's hard is knowing *which market is
worth working* and *who in it is worth a conversation*. So every run answers
both:

- `markets.csv` — each city scored 0-100 on lead density, contactability,
  channel fit and how many operators are independent rather than chains.
- `leads.csv` — each business scored 0-100 against your ICP, tiered A/B/C,
  with a `score_reasons` column explaining exactly why.

## What it pulls per business

| Source | Fields |
|---|---|
| Google Places | name, phone, website, address, rating, review count, business status, Maps URL |
| The business's own website | email, WhatsApp click-to-chat number, Instagram, Facebook, booking platform in use, whether there's only a contact form |
| Derived | E.164 phone, chain detection, ICP fit score, tier, score reasons |

The website signals are the valuable part. A `wa.me` link and 40 reviews tells
you far more about whether someone will buy a messaging product than an
address ever will.

---

## 1. Get a Google Places API key

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and
   create or select a project.
2. Enable the **Places API**: APIs & Services → Library → "Places API" →
   Enable.
3. APIs & Services → Credentials → Create Credentials → API key.
4. Restrict the key to the Places API (and to your IP if you can), so it's
   useless to anyone else if it leaks.
5. Enable billing. Google gives a monthly free credit, but Text Search and
   Place Details are billed beyond it — see
   [pricing](https://developers.google.com/maps/billing-and-pricing).

## 2. Install

Requires **Python 3.9+**.

```bash
git clone https://github.com/anjuneedham/lead-gen-tool
cd lead-gen-tool
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## 3. Set your key

```bash
export GOOGLE_PLACES_API_KEY="your-key-here"
```

or put `GOOGLE_PLACES_API_KEY=your-key-here` in a `.env` file (gitignored),
or pass `--api-key` on each run.

## 4. Run it

### Single city

```bash
python find_leads.py scan --category car_rental --city Lisbon --country Portugal --language pt --region pt
```

### Many markets, ranked

```bash
cp markets.example.yml markets.yml     # then edit it
python find_leads.py research --config markets.yml --dry-run   # see the cost first
python find_leads.py research --config markets.yml --out-dir out/
```

`--dry-run` prints the full plan and estimated API call count **without
spending anything or even needing a key**. Always start there.

Output lands in `out/`:

```
out/leads.csv     every lead, best fit first
out/markets.csv   markets ranked by opportunity
out/run.json      config, weights, API usage, timings — provenance for the run
```

## Configuring the research

Everything interesting lives in `markets.yml`. See
[`markets.example.yml`](markets.example.yml) for a fully commented file with
nine real markets across Europe, Latin America, Southeast Asia and Africa.

The ICP weights are the model — they're meant to be argued with:

```yaml
icp:
  weights:
    uses_whatsapp: 35        # already lives on the channel you sell
    independent: 20          # decision is local, not at head office
    reachable_email: 15
    right_size: 15           # big enough to hurt, small enough to buy
    has_booking_engine: -10  # already pays for software — longer sale
  review_count_range: [5, 400]
  min_rating: 3.5
  exclude_chains: true
```

Because every lead exports its `score_reasons`, when a result looks wrong you
can see which weight caused it and retune rather than guess.

### Worldwide options

- `language` — ISO 639-1 code. Returns names in the local language instead of
  transliterated English.
- `region` — ccTLD. Biases ranking to that country, which matters for
  ambiguous names (Córdoba exists in both Spain and Argentina).
- `areas` — a list of neighbourhoods. Google caps Text Search at **60 results
  per query**; each area runs as its own query and results are deduplicated by
  `place_id`, which is how you cover a dense city properly.
- Phone numbers are normalized to E.164 (`+351211234567`) so they're usable
  by a dialer, a CRM, or WhatsApp.
- CSVs are written UTF-8 with BOM so Excel opens non-Latin business names
  correctly.

## Command reference

| Flag | Applies to | Description |
|---|---|---|
| `--category` | scan | Preset (`car_rental`, `property_rental`, `airbnb_rental`, `boat_rental`, `tour_operator`) or free text |
| `--city` / `--country` | scan | Where to search |
| `--language` / `--region` | scan | Localization and country bias |
| `--max-results` | scan | Businesses to fetch (Google caps one query at 60) |
| `--legacy-columns` | scan | Write the original 6-column CSV |
| `--config` | research | Path to the YAML config |
| `--out-dir` | research | Where to write outputs (default `out/`) |
| `--max-per-market` | research | Override the config's cost dial |
| `--dry-run` | research | Show plan and cost estimate, spend nothing |
| `--skip-email-crawl` | both | Places data only — much faster, far less signal |
| `--no-cache` / `--cache-file` | both | Control the local API response cache |
| `--ignore-robots` | both | Crawl pages `robots.txt` disallows (off by default) |
| `--site-delay` | both | Seconds between requests to a business site |

The original flag-only form still works: `python find_leads.py --city Austin`
is treated as `scan`.

## Cost control

Place Details is the expensive half, billed per call and per field tier.

- **`--dry-run` first**, always. It prints the exact call count.
- **`max_per_market`** is the main dial. Start at 10-20 and scale once the
  results look right.
- **Responses are cached** to `.leadgen-cache.json` (30-day TTL). Re-running
  to retune ICP weights costs nothing — only genuinely new lookups bill.
- **`--skip-email-crawl`** skips website crawling entirely when you only need
  phone and address.

## Being a good citizen

- `robots.txt` is respected by default; `--ignore-robots` exists but leave it
  alone.
- Requests to any single site are delayed (1.5s default) and capped at the
  homepage plus 2 contact/about pages.
- Only publicly published pages are read — nothing behind a login, no captcha
  evasion, no social-platform scraping.
- Read the compliance notes in [WORKFLOWS.md](WORKFLOWS.md) before running
  outreach across jurisdictions — GDPR, CASL and Germany's UWG all have teeth,
  and many small operators are sole traders, which makes their details
  personal data.

## Troubleshooting

**`REQUEST_DENIED`** — the usual first-run error: wrong key, Places API not
enabled, billing off, or a key restriction blocking the call. Redo step 1.

**`OVER_QUERY_LIMIT`** — out of quota or billing isn't enabled. The tool
retries with backoff, then exits non-zero.

**Most emails are blank** — expected, and not a failure. Many small operators
publish only a contact form. That's why `contact_form_only` is a *positive*
scoring signal and why phone and WhatsApp columns exist.

**Fewer results than expected** — Google caps Text Search at 60 per query. Add
`areas` to the market to break past it.

The tool exits non-zero on setup errors, so it's safe to chain in a script.

## Limitations

- Email discovery is best-effort: JS-rendered contact details, images, and
  third-party obfuscation all defeat a plain HTML crawl.
- Chain detection is a name-match against a maintained brand list
  (`leadgen/scoring.py`) — a local franchise under an unusual name may slip
  through, and you should add regional chains for markets you work often.
- Google's category matching is fuzzy. Review results for relevance,
  especially in categories with local-language names.
- Review count is a rough proxy for business size — good enough to sort by,
  not a substitute for judgement.
- Opportunity scores compare markets *to each other within one run*. They're
  a ranking, not an absolute measure.

## Project layout

```
find_leads.py            CLI: scan and research modes
markets.example.yml      commented config with nine worldwide markets
leadgen/
  config.py              config loading and validation
  places.py              Google Places client (language/region/pagination)
  enrich.py              website crawling and signal extraction
  scoring.py             chain detection, ICP fit, market opportunity
  research.py            orchestration and phone normalization
  export.py              CSV/JSON writers
  cache.py               on-disk API response cache
WORKFLOWS.md             the processes this feeds, and compliance notes
```
