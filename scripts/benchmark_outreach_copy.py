from __future__ import annotations

import os
from itertools import combinations

import psycopg
from psycopg.rows import dict_row

from app.integrations.openrouter import CLAIM_TOKEN
from app.integrations.openrouter_constrained import ConstrainedOutreachClient
from app.outreach_policy import OUTREACHABLE_SIGNALS, client_facing_claim
from app.services.outreach_evidence import RecipientEvidence, recipient_finding_block
from app.services.outreach_similarity import structural_similarity
from app.services.outreach_verification import OutreachClaimVerifier


TARGET_OUTPUTS = 10
SCAN_LIMIT = 40


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    model = os.environ["OPENROUTER_MODEL"]
    api_key = os.environ["OPENROUTER_API_KEY"]

    if model != "qwen/qwen3-30b-a3b-instruct-2507":
        raise RuntimeError(f"Expected production Qwen model, got {model}")

    generator = ConstrainedOutreachClient(api_key=api_key, model=model)
    verifier = OutreachClaimVerifier(timeout_seconds=10.0)

    with psycopg.connect(
        database_url,
        row_factory=dict_row,
        options="-c default_transaction_read_only=on",
    ) as conn:
        prospects = conn.execute(
            """
            select
                b.place_id,
                b.name,
                b.city,
                b.vertical,
                b.website_url,
                we.resolved_url,
                coalesce(f.needs_manual_check, false) as needs_manual_check,
                b.rating,
                b.review_count,
                b.last_review_days,
                b.recent_reviews_90d,
                coalesce(seg.confirmed_trading, false) as confirmed_trading,
                coalesce(seg.established, false) as established
            from businesses b
            join v_lead_segments seg
              on seg.place_id = b.place_id
            left join website_enrichment we
              on we.place_id = b.place_id
            left join v_lead_findings f
              on f.place_id = b.place_id
            where seg.established = true
              and coalesce(b.review_count, 0) >= 10
              and coalesce(f.needs_manual_check, false) = false
              and coalesce(we.resolved_url, b.website_url) is not null
              and cardinality(coalesce(we.emails_found, '{}'::text[])) > 0
              and not exists (
                    select 1
                    from suppression s
                    where lower(s.email) = lower(coalesce(we.emails_found[1], ''))
              )
              and exists (
                    select 1
                    from v_lead_audit_detail d
                    where d.place_id = b.place_id
                      and d.signal in (
                          'no_website',
                          'no_ssl',
                          'no_title',
                          'no_localbusiness_schema'
                      )
              )
            order by
                b.review_count desc nulls last,
                b.rating desc nulls last,
                b.name asc
            limit %s
            """,
            (SCAN_LIMIT,),
        ).fetchall()

        results: list[dict] = []
        scanned = 0

        for prospect in prospects:
            scanned += 1
            findings = conn.execute(
                """
                select signal, finding, observed, severity, points
                from v_lead_audit_detail
                where place_id = %s
                  and signal in (
                      'no_website',
                      'no_ssl',
                      'no_title',
                      'no_localbusiness_schema'
                  )
                order by
                    case severity
                        when 'critical' then 1
                        when 'high' then 2
                        when 'medium' then 3
                        when 'low' then 4
                        else 5
                    end,
                    points desc,
                    signal
                """,
                (prospect["place_id"],),
            ).fetchall()

            context = {**prospect, "findings": findings}

            try:
                verified = verifier.verify(context)
            except Exception as exc:
                print(f"SKIP {prospect['name']}: verifier {type(exc).__name__}: {exc}")
                continue

            if verified.signal not in OUTREACHABLE_SIGNALS:
                continue

            technical_claim = client_facing_claim(verified.signal, verified.text)
            if not technical_claim:
                continue

            evidence = RecipientEvidence.from_row(prospect)
            finding_block = recipient_finding_block(
                business_name=prospect["name"],
                technical_claim=technical_claim,
                evidence=evidence,
            )

            try:
                copy = generator.generate_email(
                    business_name=prospect["name"],
                    city=prospect.get("city"),
                    vertical=prospect.get("vertical"),
                    verified_claim=finding_block,
                )
            except Exception as exc:
                print(f"SKIP {prospect['name']}: generator {type(exc).__name__}: {exc}")
                continue

            if copy.body.count(CLAIM_TOKEN) != 1:
                print(f"SKIP {prospect['name']}: verified token contract failed")
                continue

            rendered = copy.body.replace(CLAIM_TOKEN, finding_block)
            results.append(
                {
                    "name": prospect["name"],
                    "rating": prospect.get("rating"),
                    "review_count": prospect.get("review_count"),
                    "signal": verified.signal,
                    "finding": finding_block,
                    "subject": copy.subject,
                    "body": rendered,
                    "model": copy.model,
                }
            )

            if len(results) >= TARGET_OUTPUTS:
                break

    print("=" * 100)
    print("REAL PROSPECT OUTREACH BENCHMARK")
    print("=" * 100)
    print(f"Model: {model}")
    print(f"Scanned: {scanned}")
    print(f"Generated: {len(results)}/{TARGET_OUTPUTS}")

    for index, item in enumerate(results, 1):
        print()
        print("=" * 100)
        print(f"{index}. {item['name']}")
        print("=" * 100)
        print(f"Google: {item['rating']} / {item['review_count']} reviews")
        print(f"Verified signal: {item['signal']}")
        print(f"Generator: {item['model']}")
        print(f"Subject: {item['subject']}")
        print()
        print(item["body"])

    print()
    print("=" * 100)
    print("STRUCTURAL SIMILARITY")
    print("=" * 100)

    pairs = []
    for first, second in combinations(results, 2):
        ratio = structural_similarity(
            first["body"],
            candidate_business_name=first["name"],
            candidate_verified_claim=first["finding"],
            existing_body=second["body"],
            existing_business_name=second["name"],
            existing_verified_claim=second["finding"],
        )
        pairs.append((ratio, first["name"], second["name"]))

    pairs.sort(reverse=True)
    for ratio, first, second in pairs[:15]:
        marker = "BLOCK" if ratio >= 0.82 else "PASS "
        print(f"{marker} {ratio:.3f}  {first} <-> {second}")

    print()
    print("=" * 100)
    print("HARD CHECKS")
    print("=" * 100)

    forbidden = (
        "authority score",
        "total score",
        "tier ",
        "top 4%",
        "loads quickly",
        "displays correctly",
        "visible error message",
        "hi richard",
    )
    for item in results:
        lowered = item["body"].lower()
        hits = [term for term in forbidden if term in lowered]
        print(f"{item['name']}: {'PASS' if not hits else 'FAIL ' + str(hits)}")

    print()
    print("=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(f"Generated: {len(results)}/{TARGET_OUTPUTS}")
    if pairs:
        print(f"Highest similarity: {pairs[0][0]:.3f}")
        print(f"Pairs >= 0.82: {sum(1 for ratio, _, _ in pairs if ratio >= 0.82)}")
    print(f"Unique subjects: {len({item['subject'].lower() for item in results})}/{len(results)}")
    print(f"Unique bodies: {len({item['body'] for item in results})}/{len(results)}")
    print("DATABASE SESSION: READ ONLY")
    print("NO QUEUE WRITES. NO GMAIL DRAFTS. NOTHING SENT.")


if __name__ == "__main__":
    main()
