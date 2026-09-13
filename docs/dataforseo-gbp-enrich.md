# DataForSEO GBP Deep Enrichment — OPTIONAL add-on

**Status: built but NEVER RUN against a live account.** Mike had not signed up as
of build time. Step 3 below exists specifically to catch anything I got wrong
about the response shape. Do not skip it.

## Why this exists

Google's own Business Profile APIs expose `serviceItems`, the owner-written
description, and review replies — but only for locations the **owner** has
authorized you to manage. Google's API policy says so explicitly:

> "You can only use the Business Profile APIs to create, manage, and report on
> business listings that you either own or are authorized to manage."

Places API (New) doesn't have these fields at all — no owner-reply field exists
anywhere in its review object, no services, no owner description.

So the only route to these three qualifiers, for a business you don't manage, is
a provider that scrapes. DataForSEO is the pick because it's the only one
confirmed to return **both** `services[]` (added July 2026) and `owner_answer`,
and it's the cheapest at roughly **$1.50–$3.00 per 1,000 profiles**.

## SETUP — when you're ready, not before

**1. Create the account**
- Sign up at dataforseo.com. Minimum top-up is small; start with the minimum.
- Go to **Dashboard → API Access**. Copy your **login email** and the **API
  password**. The API password is NOT your website login password — this trips
  everyone up.

**2. Enter both on this skill's credentials card.**

**3. VERIFY BEFORE SPENDING ANYTHING.** Run:

```
python3 gbp_deep.py --verify "Blackwood Electric" --city Oceanside
```

This makes exactly two calls (under a cent) and prints the **raw JSON** followed
by what `extract()` parsed out of it. Compare them line by line.

If a value shows `None` or `0` in the parsed block but is visibly present in the
raw JSON, then my field path is wrong — fix `extract()` in `gbp_deep.py` before
running any batch. The paths I wrote follow DataForSEO's documented structure but
were never executed, and every `.get()` chain is defensive, which means a wrong
path silently returns "no data" rather than erroring. That failure mode looks
exactly like "this business has no services listed," which would put a false
claim in an email.

Specifically confirm these five:
- `services` (or `service_items`) — a list, with `snippet`/`description` per item
- `description` — the owner-written bio
- `is_claimed`
- `owner_answer` on review items
- `timestamp` on review items

**4. Apply the schema** (only if you want it in Supabase): run
`gbp_deep_schema.sql` in the SQL Editor. Adds the `gbp_deep` table and the
`v_leads_enriched` view.

## Usage

Nothing runs without an explicit spend confirmation. Default target is the
established segment — recently active, at or above the local median on reviews.

```bash
# See what it would cost, without spending
python3 gbp_deep.py --segment established --limit 20

# Actually run it
python3 gbp_deep.py --segment established --limit 20 --yes

# Specific leads you're about to contact — the intended everyday path
python3 gbp_deep.py --place-ids ChIJxxx ChIJyyy --yes

# Halve the cost, lose the review-reply data
python3 gbp_deep.py --segment established --no-reviews --yes

# Whole sweep. Prints an estimate; refuses above --max-spend (default $2)
python3 gbp_deep.py --all --max-spend 5 --yes
```

## Cost discipline

Measured against the San Diego electrician sweep (244 businesses):

| Scope | Cost |
|---|---|
| Top 20 you're about to contact | ~$0.12 |
| The 60 established leads | ~$0.36 |
| All 244 | ~$1.46 |

**Enrich the shortlist, not the sweep.** The free pipeline already narrows 244 →
149 trading → 60 established. Paying to enrich businesses you'll never contact is
the only way this gets expensive.

**Caching is the real cost control.** Results cache for 30 days in
`gbp_deep_cache.json` and cached entries are skipped automatically. Services
lists and descriptions barely change; review replies change slowly. Without the
cache a weekly sweep re-buys the same profiles four times a month for no new
information.

## What it adds to scoring

Three signals, up to 34 points on the GBP axis, and the axis maximum widens to
match so an enriched lead isn't scored against a narrower scale:

- `no_services_listed` (12) — empty Services list
- `no_business_description` (8) — 750 characters left blank
- `no_review_replies` (14) — zero replies across the sampled reviews
- `unclaimed_profile` (10) — profile appears unclaimed
- plus lighter variants for thin descriptions and partial reply rates

**Deep signals only ever ADD.** A lead with no deep data scores on the free
signals alone — never penalised for the absence. `test_scoring.py` asserts this,
along with the requirement that enriching one lead leaves others' scores
untouched.

## The best opener in the whole pipeline

`no_review_replies` is the strongest cold-outreach angle available anywhere in
this system: visible to the prospect, undeniable, and it reads as attentive
rather than salesy. "You've got 40 reviews and haven't replied to any of them"
lands very differently from a PageSpeed number.

**But verify it live before sending.** Scraped fields drift, and this project has
already shipped four separate classes of false claim from trusting cached data
over a live check — sites reported down that were merely bot-blocked, phantom
phone mismatches, a web developer's email, an out-of-state business. Add
`no_review_replies` to the live-verification path in `outreach.py` before it ever
appears in an email.

## Failure posture

If DataForSEO is down, changes its response shape, or the account runs out of
credit, the free pipeline keeps working unchanged. This skill is strictly
additive and can be abandoned at any time with no migration.