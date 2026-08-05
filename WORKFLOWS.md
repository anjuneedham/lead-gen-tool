# Lead generation workflows worth automating

Notes on the processes that actually move the needle, which parts this tool
already does, and where you'd plug in the rest. Ordered roughly by return on
effort.

Throughout: **automate research and qualification, keep contact manual.**
Automated outreach is what turns a good list into a burned domain and a
blocked WhatsApp number. Everything below is designed so a human sends the
first message.

---

## 1. Pick the market before you pick the leads

Most teams skip straight to prospecting and never ask whether the market is
worth working. Scanning ten cities and comparing them on lead density,
contactability and channel fit costs a few dollars of API budget and can
save weeks of pointless outreach.

**Status: built in.** `research` mode scores each market 0-100 on:

| Component | Weight | Why it matters |
|---|---|---|
| Qualified-lead density | 40% | Whether there's enough business to justify the effort |
| Contactability | 25% | A market you can't reach isn't a market |
| WhatsApp adoption | 20% | Channel fit — are they already where you sell |
| Independent share | 15% | Whether the buying decision is local |

Re-run it quarterly. Markets shift, especially seasonal ones.

## 2. Define an ICP as weights, then close the loop

An ICP written in a slide deck does nothing. An ICP written as weights
scores every lead automatically, and — the part most teams miss — can be
corrected by what actually closes.

**Status: built in** (`icp.weights` in `markets.yml`; every lead carries a
`score_reasons` column explaining its number).

**The loop to add:** after ~30 closed/lost outcomes, compare win rate by
tier. If tier-B converts as well as tier-A, your weights are wrong. Export
won deals, look at which signals they share, raise those weights. This is
the single highest-value thing you can do and it takes an hour a quarter.

## 3. Waterfall enrichment — cheap sources first

Don't pay to enrich every lead. Run free signals first, score, then spend
money only on the leads that scored well.

```
Places API (name, phone, site, rating, reviews)   ~$0.02/lead
        ↓  score, drop chains and closed listings
Website crawl (email, WhatsApp, socials, platform)  free
        ↓  keep tier A/B only
Paid enrichment for the survivors                  $0.10-1.00/lead
```

**Status: first two tiers built in.** The third is where you'd add a paid
provider — decision-maker names, company size, funding. Feed the tool's
`leads.csv` in, and only for rows where `tier` is A or B.

## 4. Trigger-based prospecting (timing beats targeting)

The same pitch lands very differently depending on when it arrives. Triggers
worth watching in this space:

- **Review velocity spike** — a business getting busier is a business whose
  enquiry volume just became painful. Re-scan monthly and diff `review_count`;
  the biggest movers are your warmest calls.
- **Seasonal ramp** — pitch a Croatian rental operator in February, not July.
  When they're in season they have no time; before it, they're planning.
- **New listings / new licence registers** — many cities publish short-term
  rental licence registers. A brand-new licence is an operator setting up
  their process right now.
- **Hiring signals** — a small operator advertising for a "reservations
  assistant" has just told you their enquiry volume outgrew their staff.
- **Website changes** — a new booking widget, or a WhatsApp button appearing.

**Status: the diff is easy to add** — the cache already stores prior runs, so
comparing two `leads.csv` files by `place_id` gives you movers. That's the
next feature I'd build.

## 5. Deduplicate and suppress, permanently

The fastest way to destroy your reputation is to contact the same business
three times because it appeared in three scans.

Keep a persistent file of every business ever contacted, keyed on
`place_id` (stable, unlike names and phone numbers), plus:

- **Do-not-contact list** — anyone who asked, forever, no exceptions.
- **Cooldown** — don't re-approach a "no" for 6-12 months.
- **Ownership** — who on your team owns the relationship.

**Status: `place_id` is exported for exactly this.** Filter new runs against
your contacted list before working them.

## 6. Sequence channels by market, not by habit

Channel norms are regional, and getting this wrong reads as foreign spam:

- **Latin America, Southern Europe, Southeast Asia, Middle East** — WhatsApp
  is normal for business. A short, plain message is fine and expected.
- **Germany, Austria, Switzerland** — phone and email; unsolicited WhatsApp
  reads as intrusive, and German competition law is strict about it.
- **US/UK/Canada** — email first, LinkedIn second; phone is acceptable B2B.

**Status: partly built.** The `whatsapp` and `phone_e164` columns tell you
what's available per lead; the market's `notes` field is where you record the
local convention. The tool does not send anything on any channel — by design.

## 7. Hand off to a CRM, don't live in spreadsheets

A CSV is fine for a first pass and terrible as a system of record. Once you
have a repeatable motion, import into any CRM and map `fit_score` → lead
score, `tier` → priority, `score_reasons` → the note the rep reads first.

The `run.json` file gives you provenance — which config, which weights, when
— so a lead's score is reproducible six months later.

## 8. Build a referral loop before you scale outbound

In fragmented local markets, operators know each other. One happy customer in
Lisbon is worth more than 200 cold contacts. Ask for one introduction at the
point the customer first says something positive — not at renewal.

This has no automation and outperforms most things that do.

## 9. Let inbound capture the demand outbound creates

Outbound makes people search for you rather than reply to you. A landing page
per market, in the local language, with the same WhatsApp button your leads
use, converts the ones who ignored the first message.

## 10. Measure the funnel by tier, or you're guessing

Minimum viable tracking, per market and per tier:

```
leads → contacted → replied → call booked → won
```

If tier-A doesn't out-convert tier-C, the scoring model is wrong, and every
hour spent on the list is being allocated by a broken model. This is the
feedback that makes §2 work.

---

## Compliance — worldwide means many jurisdictions

Not legal advice, and it varies by country. What matters in practice:

- **Business contact details published on a company's own website** are the
  safest category to collect and use for B2B contact. Role addresses
  (`info@`, `reservations@`) are far safer than a named person's address.
- **GDPR (EU/UK)** covers sole traders and named individuals — a lot of small
  rental operators are exactly that. You need a lawful basis (legitimate
  interest is the usual one for B2B), you must identify yourself, and you must
  honour objections immediately and permanently.
- **Germany** additionally restricts unsolicited commercial contact under UWG
  — take local advice before cold outreach there.
- **CAN-SPAM (US)**, **CASL (Canada)**, **LGPD (Brazil)**, **POPIA (South
  Africa)** all impose their own requirements; CASL is notably strict and
  consent-based.
- **WhatsApp's Business Terms** prohibit unsolicited bulk messaging outright.
  Manual, individual, relevant messages are a different thing from a blast —
  stay firmly on that side of the line.

Practical rules that keep you clear of most of this: contact businesses not
people, keep volume low and messages specific, identify yourself, and honour
every opt-out permanently on first request.

## What this tool deliberately does not do

No sending, on any channel. No contact-detail harvesting from social profiles
or platforms whose terms forbid it. No scraping behind logins. No bypassing
`robots.txt` unless you explicitly override it, and no captcha evasion.

The bottleneck in lead generation is rarely volume — it's relevance and
timing. Everything above optimizes for those.
