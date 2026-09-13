# Lilos Growth — Lead Aggregator

Finds home-service businesses with visible GBP/website gaps in a target geo,
scores them by how badly they need Lilos Growth's services, attaches contact
data, and generates verified outreach copy.

## Setup

1. **Google Cloud** — enable **Places API (New)** + **PageSpeed Insights API**, create an API key.
2. **Supabase** — run `schema.sql` then `views.sql` in the SQL Editor.
3. Credentials go on the skill card. Google key must be **"Readable by scripts"** (Advanced) — it's sent as `X-Goog-Api-Key` to one host and a URL param to another, so proxy mode cannot deliver it.
4. Verify with `python3 check_creds.py` — reports which keys arrived and whether each service actually works.

## Running a sweep

Single commands cap at **5 minutes**, and backgrounding does not escape it. Use the staged driver:

```bash
python3 discover.py --verticals electrician --out discovered.json   # ~25s, 78 calls
python3 pipeline.py crawl --batch 80        # repeat until 0 remaining (~40s/80 sites)
python3 pipeline.py psi   --batch 20        # slow; only the top slice is worth it
python3 pipeline.py status                  # what's left
python3 pipeline.py finalize --out leads.csv
```

`pipeline.py` caches to `enrichment_cache.json` and saves incrementally, so a
timeout never loses work. Re-scoring from cache is free.

## Cost

Billing is **per request, not per result** — one Text Search call returns 20
fully-detailed places if the field mask includes the Enterprise fields
(`websiteUri`, `nationalPhoneNumber`, `rating`, `userRatingCount`,
`regularOpeningHours`). That's ~$1.75/1,000 businesses vs ~$20 calling Place
Details per business. **Never call Place Details in the bulk sweep.**

Free tier per month, no rollover: Essentials 10,000 / Pro 5,000 / **Enterprise 1,000**.
Measured: San Diego County electricians = 261 businesses on 78 calls = **$0**.

Hard caps: 20 results/page, 60 results / 3 pages per query, each page billed.

## Scoring

```
opportunity = gbp_gap * 0.5 + website_gap * 0.5
total       = opportunity * reachability_multiplier(0.40 … 1.00)
```

Reachability **multiplies** rather than adds — being easy to contact is not an
opportunity, and as an additive term it hands free points to flawless
businesses. Axes normalize against realistic maxima (`GBP_MAX_POINTS = 77`,
`WEBSITE_MAX_POINTS = 93`); update those constants when adding signals or scores
drift silently. Run `test_scoring.py` after any weight change.

## KNOWN GAP: the model scores gap, not fit

First live run: tier A had a **median of 3 reviews**, and 42/44 tier-A leads had
no website. A one-review business with no site is a guy with a truck — not a
buyer for a 30-page build. Wheyland Electric, the reference client, has 47
reviews. Filtering to 15+ reviews AND score ≥30 left **11 of 261**.

**Not yet implemented:** a viability multiplier using review count as a revenue
proxy (discount under ~8, peak 15–80, taper above). Until then, always pass
`--min-reviews` when generating outreach.

## Structural fact: gap and email-reachability are inversely correlated

Emails come from crawling the prospect's website. The highest-gap leads have no
website, therefore no email. Automated email will systematically hit your
*weaker* opportunities. Hence two queues: `v_leads_call_list` (phone, high
value) and `v_leads_email_list` (automatable). Don't merge them.

## Verify before you assert — four false-positive classes found in testing

Every one of these was caught only by manually checking a claim against reality.
The cache is not evidence.

1. **Bot blocks read as downtime.** 2 of 3 sites flagged "does not load" were healthy behind a WAF (403). Now retried with a browser UA and quarantined as `blocked_*`, never scored as down.
2. **Phantom NAP mismatches.** A loose phone regex matched script/CSS digits, then the list was truncated to 5 *before* comparison, cutting the real number. 3 of 4 "your phone doesn't match" claims were false. Fixed, but `nap_mismatch` is now in `UNSAFE_TO_ASSERT` — good for ranking, not for claiming.
3. **The developer's email.** `micah@micahrich.com` was harvested off a "site by" footer credit. Emails are now kept only if the domain matches the site or is a consumer mailbox.
4. **Out-of-area results.** A Phoenix business matched a San Diego query — Text Search's `locationBias` is a hint, not a geofence. Coordinates are now verified against the bounding box.

Also unreliable: `photo_count` from Text Search (an absent `photos` field is
indistinguishable from zero), so `no_photos` is in `UNSAFE_TO_ASSERT`.

**The systemic fix is `verify_claim()` in outreach.py** — it re-fetches the live
site and confirms the specific claim before writing the email, swapping to a
different angle if it fails. One HTTP request per email eliminates the whole
class. Keep it.

## Outreach copy

`python3 outreach.py --limit 5 --min-reviews 10 --preview`

Angle selection is **distinctiveness-based with batch diversity**: pick the
rarest signal this business has, then penalise angles already used in the batch.
Ranking by a fixed priority ladder makes every email identical, and ranking by
rarity alone collapses the batch onto whichever rare signal is shared — both
were observed. Name guessing requires two consecutive non-trade tokens
("Bob Greer Electric" → "Bob"; "Blackwood Electric" → neutral greeting), because
"Hi Blackwood," is worse than no name.

Sending goes through the Gmail integration (draft-first), never from inside
these scripts. `LILOS_ADDRESS` must be set — CAN-SPAM requires a physical
address, and the placeholder is deliberately loud.

## Gotchas
- Supabase over **PostgREST only**; port 5432 is firewalled and fails like an auth error.
- Python 3.9 — every module needs `from __future__ import annotations`.
- Skill credentials expire mid-session; re-run `FetchSkillScripts` when a run reports expiry.
- PageSpeed ~10–30s/site, ~4 QPS. Batch ≤22 and rely on incremental saves.


## RUNNING A SWEEP — exact sequence

Single commands cap at 5 minutes and backgrounding does not escape it. Always
staged, always via RunWithCredentials, always from the skill's script directory:

```bash
python3 discover.py --verticals plumber --out discovered.json   # ~25s
python3 pipeline.py crawl --batch 80        # repeat until "0 remaining"
python3 pipeline.py psi   --batch 20        # optional, slow; top slice only
python3 pipeline.py finalize --out leads.csv
python3 make_dashboard_data.py              # builds dashboard_data.json
python3 build_dashboard.py                  # builds dashboard.html
```

Then SaveFile the HTML and PublishFilePublicly it so Mike gets a URL.

`--verticals` accepts any key from `VERTICALS` in config.py: electrician,
plumber, hvac, roofing, restoration, landscaping, party_rentals, handyman.
Multiple are fine: `--verticals plumber hvac roofing`.

To change city or geography, edit `GEO_BBOX`, `TARGET_CITIES`, and `GEO_LABEL`
in config.py. The bbox is verified per-result, so a stale bbox silently drops
everything in the new area — update it before sweeping a new county.

## Liveness — the qualifier that replaced review count

`review_activity()` reads `publishTime` off the reviews Google returns and
records `last_review_days`. This separates a dormant 2019 listing from a working
business that never asks for reviews; review COUNT cannot.

Two things that bit hard here:

1. **Google emits NANOSECOND precision** (`.857842623`). Python 3.9's
   `fromisoformat` raises on 9 fractional digits, and a bare try/except turned
   every timestamp into "no data" — it reported 0 active businesses out of 248,
   which is the only reason it got noticed. Timestamps are now truncated to
   microseconds before parsing.
2. **Google returns the 5 most RELEVANT reviews, not the 5 most recent** —
   confirmed by inspecting raw payloads where publishTimes come back out of
   chronological order. So `last_review_days` is a LOWER BOUND: recent proves
   alive, old does NOT prove dormant. `ACTIVITY_TIERS` is deliberately
   asymmetric for this reason. Do not "fix" it into a symmetric penalty.

## Category mismatch

`primary_type` vs the vertical's expected types, but only claimed when the
business NAME corroborates the trade — otherwise we'd tell a plumbing company
its category is wrong for appearing in an electrician search. Separately,
`wrong_vertical()` in discover.py EXCLUDES foreign businesses entirely (auto
electric shops, hardware stores) rather than scoring them as mis-categorised.

## The established segment

`make_dashboard_data.py` marks `est = confirmed trading AND reviews >= local
median AND 2+ real gaps`. This is the dashboard's default view and the segment
Mike said he actually wants — established businesses with unmanaged marketing,
not micro-operators with the biggest raw gap.

**Open question Mike has not yet answered:** score still ranks by gap SIZE, so
no-website micro-businesses top the All view while a 201-review shop with a bad
site sits at tier D. Whether to reweight toward established is his revenue
judgment. Ask before changing it.


## CRITICAL: the Places paging contract (fixed 2026-08-13)

Paging requests must **repeat every parameter from the initial request** next to
`pageToken`. Sending `{"pageToken": tok}` alone returns:

> HTTP 400 — "Empty text_query. Request parameters for paging requests must match
> the initial SearchText request."

Verified empirically (`test_paging.py`): page 1 returns 20 places; token-only
page 2 returns 0 with a 400; parameters-repeated page 2 returns 17 new places.

**Every sweep before this fix was truncated at 20 results per query.** The
electrician sweep of 244 was an undercount; re-running with the fix returned 256.
Plumbers gained 43. The failure was silent in practice because `sweep()` catches
per-query exceptions and prints `!! query: error` — and those lines get lost when
output is piped through `tail`. **Count error lines explicitly** after a
discovery run:

```
python3 discover.py --verticals X 2>&1 | grep -c '^  !!'
```

Do not "simplify" the paging payload back to token-only. `test_paging.py` exists
to catch that regression.

## Result stability — measured, not assumed

- Two identical sweeps minutes apart: **identical** 256 businesses, 0 new on merge.
- A sweep 18 hours earlier: **34 gained / 22 lost**, including a 1,740-review
  company that disappeared from the later run.

So results are stable within a session and drift across days. Re-running
immediately buys nothing. Re-running weekly with `--merge` accumulates genuine
coverage instead of replacing the set and silently losing businesses Google
didn't surface that day. Supabase already unions on place_id; the LOCAL
`discovered.json` does not unless you pass `--merge`, and the dashboard reads the
local file — so without `--merge` the dashboard shows less than the database knows.

## Skill-persistence trap — check this every time

Fixes made in a thread's sandbox do NOT reach the skill until an
UpdateSkillAndScripts card is **confirmed by the user**. This has now bitten
twice: the plumber sweep documented five fixes as "persisted back to the skill,"
but the skill still contained the original code for all five (verified by
grepping for `_scan_contacts`, `home_goods_store`, `--run-id` — none present).

Before relying on a fix from a previous run, grep the fetched scripts for it.
After making a fix, state plainly that the card must be clicked, and do not
describe the fix as saved until it is.


## Crawl durability — three defects fixed 2026-08-27 (plumber sweep)

The crawl stage used to lose whole batches. Three separate causes, all observed
directly, all now fixed in `cmd_crawl`:

1. **Save-at-the-end.** `cmd_crawl` called `save_cache()` once after the entire
   batch. Any batch that hit the 5-minute execution cap discarded everything it
   had crawled — 270s of work vanished with the status counter stuck at 80.
   `cmd_psi` had saved incrementally for exactly this reason; crawl did not.
2. **`requests` timeout is not a total cap.** `CRAWL_TIMEOUT_S = 15` is a
   BETWEEN-BYTES socket timeout. A server that stalls before its status line, or
   trickles a chunked body, parks a worker indefinitely. Thread dumps showed
   workers stuck in `http/client.py:_read_status` and `urllib3 read_chunked` for
   45s+ under a 15s timeout.
3. **`_robots_ok` had no timeout at all.** `RobotFileParser.read()` calls
   `urllib.request.urlopen` with no timeout argument — an unbounded hang.
   robots.txt is now fetched with `requests` under `CRAWL_TIMEOUT_S` and passed
   to `rp.parse()`.

**Threads cannot be cancelled.** A future-level timeout does not free a worker
blocked in a socket read, and `ThreadPoolExecutor.shutdown()` joins those
threads, so the stage could not return either. The crawl stage therefore uses
**`ProcessPoolExecutor`** with a wall-clock deadline (`CRAWL_DEADLINE_S`,
default 210s, overridable by env var) and kills stalled children instead of
joining them. Do not "simplify" this back to threads.

Sites that never come back are cached as **`blocked_crawl_hang`**. The
`blocked_` prefix is load-bearing: `scoring.py` scores every OTHER unreachable
error as `site_down` — "their website does not load", **critical** — which for a
site that merely stalled our crawler is a false claim made to a business about
its own website. The `blocked_` path scores 0 and flags a manual check.

Measured after the fix: 39/40 sites in 60s, 1 quarantined, stage returned
immediately. Full 319-site plumber crawl completed in ~5 batches.

## outreach.py is 100% Supabase-dependent — and does NOT check suppression

Two things worth knowing before planning an outreach batch:

1. `outreach.py` reads candidates and evidence straight from PostgREST
   (`score_evidence`, etc.). If the Supabase project is down or paused it fails
   on the first query and **no outreach can be generated at all**, even though
   the local CSV and dashboard are complete.
2. **`outreach.py` contains no suppression check.** Suppression is enforced only
   in the Supabase VIEW `v_leads_email_list` (`views.sql` filters on the
   `suppression` table). So generating copy from local files, or from any query
   that isn't that view, silently bypasses every opt-out. Do not build a
   local-CSV fallback for outreach without porting the suppression filter first.

## segment.py was electrician-only

`segment.py` hardcoded `baselines["electrician"]` and raised
`KeyError: 'electrician'` on every other vertical. It now derives medians from
whatever verticals the sweep contains and compares each business against its own
trade's median.


## The category signal is only valid for some verticals (found 2026-08-27)

`VERTICAL_EXPECTED_TYPES` was written from what Google's **GBP category names**
look like. The Places API (New) **type** vocabulary is different and smaller, and
several expected types do not exist in it at all. An expected set that can never
be matched makes every business in that vertical look mis-categorised.

Probe the API before trusting a vertical's expected types:

```python
# searchText with includedType=<type>; an unknown type returns
# "Invalid included_type: '<type>'"
```

Measured results:

| vertical | expected types | valid? |
|---|---|---|
| electrician | `electrician` | yes |
| plumber | `plumber` | yes |
| roofing | `roofing_contractor` | yes |
| party_rentals | `event_venue` valid, `party_equipment_rental_service` invalid | partly |
| **hvac** | `hvac_contractor`, `heating_contractor`, `air_conditioning_contractor` | **none valid** |
| **handyman** | `handyman`, `general_contractor` | **none valid** |
| **landscaping** | `landscaper`, `landscape_designer`, `lawn_care_service` | **none valid** |
| **restoration** | `fire_damage_restoration_service`, `water_damage_restoration_service`, `general_contractor` | **none valid** |

HVAC is confirmed by two independent lines of evidence: the API rejects all three
type strings, AND **0 of 417** HVAC businesses in the tri-vertical sweep carried
any of them (plumber matched 334/390, roofing 266/362). Before the fix the model
raised a category claim against **301 of 417 HVAC leads** — telling ~250 owners
their primary category was wrong and naming a replacement category that does not
exist. Category claims across the sweep fell **341 -> 40** once gated.

`CATEGORY_SIGNAL_VERIFIED` in config.py is now the gate, and `scoring.py` checks
it before emitting `category_generic` or `category_mismatch`. Add a vertical only
after probing it.

**Subtlety worth remembering:** `general_contractor` is REJECTED as an
`includedType` but IS returned as a `primaryType`. The filter vocabulary and the
returned-type vocabulary are not the same list, so an `includedType` probe proves
a type is not a valid filter, which is strong evidence but not identical to
"cannot appear as primaryType." Where possible corroborate with observed
primaryType counts from a real sweep, as was done for HVAC.

## Per-vertical medians — multi-vertical sweeps were scored against the wrong bar

`make_dashboard_data.py` computed `med = list(baselines.values())[0].median_reviews`
— an arbitrary vertical's median applied to every business. On a plumber + HVAC +
roofing sweep this judged HVAC and roofing (local medians of **12**) against the
plumber median of **38**, and because it depended on dict ordering the
"established" count was not even stable. It reported 141 established; the correct
per-vertical figure is **210**.

Both `make_dashboard_data.py` and `segment.py` now compare each business against
its OWN vertical's median. When adding a new consumer of `baselines`, do the
same — this is the third time this bug class has appeared.

**Local medians vary a lot by trade**, which matters when reading the segment:
plumber 38, HVAC 12, roofing 12. "At or above the local median" is therefore a
much lower bar in HVAC and roofing, so apply an explicit `--min-reviews` (15+)
on top of it before outreach rather than treating the whole segment as qualified.

## Sandbox data files are ephemeral — save them as artifacts

The container workspace can be wiped between turns. Skill scripts are re-fetched
automatically, but `discovered.json`, `enrichment_cache.json`, `leads.csv` and
`dashboard.html` are NOT part of the skill and are simply gone — a full plumber
crawl was lost this way while Supabase was also down, forcing a re-crawl.

After a crawl completes, SaveFile `discovered.json` and `enrichment_cache.json`
as thread artifacts. They can be restored with FetchStoredFile at the start of a
later turn, which makes the expensive crawl durable even when the database is
unreachable.