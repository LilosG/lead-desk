"""
Staged, resumable pipeline driver.

The execution environment caps a single command at 5 minutes, and enriching a
few hundred sites (plus PageSpeed, which is 10-30s each) takes far longer than
that. So work is done in batches against an on-disk cache and each invocation
returns quickly. Re-running picks up exactly where it left off.

  python3 pipeline.py crawl    --batch 60   # crawl 60 uncached sites
  python3 pipeline.py psi      --batch 20   # PageSpeed the top 20 not yet done
  python3 pipeline.py status                # what's left
  python3 pipeline.py finalize [--no-db]    # score, export CSV, write PostgreSQL

Cache is keyed by place_id, so it survives crashes and is free to re-score.
"""
from __future__ import annotations
from datetime import datetime, timezone

import argparse
import json
import os
import time
from dataclasses import asdict, fields

import config as C
import discover
import enrich as E
import scoring as S
from run import export_csv, summarize

# Wall-clock cap for one crawl batch, comfortably inside the 5-minute
# execution ceiling so the final save always gets to run.
CRAWL_DEADLINE_S = int(os.environ.get("CRAWL_DEADLINE_S", "210"))

BUSINESS_FILE = "discovered.json"
CACHE_FILE = "enrichment_cache.json"


def load_businesses() -> list:
    with open(BUSINESS_FILE) as fh:
        return json.load(fh)


def load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE) as fh:
        raw = json.load(fh)
    valid = {f.name for f in fields(E.SiteFindings)}
    out = {}
    for pid, d in raw.items():
        out[pid] = E.SiteFindings(**{k: v for k, v in d.items() if k in valid})
    return out


def save_cache(cache: dict) -> None:
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({pid: asdict(f) for pid, f in cache.items()}, fh, default=str)
    os.replace(tmp, CACHE_FILE)   # atomic, so a crash mid-write can't corrupt it


def prune_cache(max_age_days: int = C.CRAWL_CACHE_MAX_AGE_DAYS) -> int:
    """Forget crawl results a new sweep shouldn't reuse. Run once per sweep.

    The cache outlives sweeps, so without this a lead keeps its first crawl
    forever: a site quarantined once stayed quarantined, and old entries never
    gain newer checks.
    """
    cache = load_cache()
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400

    def stale(f: E.SiteFindings) -> bool:
        if f.crawl_error == "blocked_crawl_hang":
            return True
        if not f.is_reachable:
            return False
        checked = (f.site_signals or {}).get("checked_at")
        if not checked:
            return True
        return datetime.fromisoformat(checked).timestamp() < cutoff

    kept = {pid: f for pid, f in cache.items() if not stale(f)}
    if len(kept) != len(cache):
        save_cache(kept)
    return len(cache) - len(kept)


def active_run_store(required: bool = False):
    from run_state import load_current_run
    from store import PostgresStore

    state = load_current_run()

    if not state:
        if required:
            raise RuntimeError(
                "no active staged run; begin with discover.py"
            )
        return None, None

    store = PostgresStore()

    if not store.ping():
        raise RuntimeError(
            "PostgreSQL unavailable for active staged run"
        )

    active = store.get_active_run()

    if not active:
        raise RuntimeError(
            "run pointer exists but PostgreSQL has no active run; "
            "use runctl.py status and resolve the stale state"
        )

    pointer_run_id = str(state["run_id"])
    database_run_id = str(active["id"])

    if pointer_run_id != database_run_id:
        raise RuntimeError(
            "run pointer does not match PostgreSQL active run: "
            f"pointer={pointer_run_id} database={database_run_id}; "
            "use runctl.py status before continuing"
        )

    return store, pointer_run_id


def cmd_status(businesses, cache) -> None:
    total = len(businesses)
    no_site = [b for b in businesses if not b.get("website_url")]
    have_site = [b for b in businesses if b.get("website_url")]
    crawled = [b for b in have_site if b["place_id"] in cache]
    reachable = [b for b in crawled if getattr(cache[b["place_id"]], "is_reachable", False)]
    psi_done = [b for b in reachable
                if getattr(cache[b["place_id"]], "psi_performance", None) is not None]
    blocked = [b for b in crawled
               if (getattr(cache[b["place_id"]], "crawl_error", "") or "").startswith("blocked_")]

    print(f"businesses          {total}")
    print(f"  no website        {len(no_site)}  (auto-scored, no crawl needed)")
    print(f"  with website      {len(have_site)}")
    print(f"    crawled         {len(crawled)}  ({len(have_site) - len(crawled)} remaining)")
    print(f"    reachable       {len(reachable)}")
    print(f"    bot-blocked     {len(blocked)}  (flagged for manual check)")
    print(f"    psi done        {len(psi_done)}")


def cmd_crawl(businesses, cache, batch: int) -> None:
    # Profiles with no website are included: the crawler first looks for the
    # business's own site (crawl_unlisted) before we call it "no website".
    todo = [b for b in businesses if b["place_id"] not in cache]
    if not todo:
        print("crawl complete — nothing left")
        return
    chunk = todo[:batch]
    print(f"crawling {len(chunk)} of {len(todo)} remaining...")

    # Three failure modes made earlier versions of this stage lose whole
    # batches. All three were observed directly on the plumber sweep:
    #
    # 1. Saving once at the end of a batch: the batch can exceed the 5-minute
    #    execution cap, and everything crawled in it is then discarded. 270s of
    #    work vanished with the progress counter stuck at 80.
    # 2. requests' `timeout` is a BETWEEN-BYTES socket timeout, not a cap on
    #    total request time. A server that trickles bytes, or stalls before
    #    sending its status line, parks a worker indefinitely despite
    #    CRAWL_TIMEOUT_S. Thread dumps showed workers stuck in _read_status and
    #    read_chunked for 45s+ under a 15s timeout.
    # 3. THREADS CANNOT BE CANCELLED. A future-level timeout does not free a
    #    worker blocked in a socket read, and ThreadPoolExecutor's shutdown
    #    joins those threads, so the stage cannot return either.
    #
    # Hence processes, which can actually be killed, plus a wall-clock deadline
    # and a save after every completion.
    from concurrent.futures import ProcessPoolExecutor, as_completed, TimeoutError as FTimeout

    deadline = time.time() + CRAWL_DEADLINE_S
    workers = C.CRAWL_MAX_CONCURRENT
    done = 0
    ex = ProcessPoolExecutor(max_workers=workers)
    futs = {ex.submit(E.crawl_business, b): b for b in chunk}
    try:
        for fut in as_completed(futs, timeout=max(5, deadline - time.time())):
            b = futs[fut]
            try:
                cache[b["place_id"]] = fut.result()
            except Exception as e:
                cache[b["place_id"]] = E.SiteFindings(
                    place_id=b["place_id"], crawl_error=f"exception: {e}"[:200])
            done += 1
            if done % 10 == 0:
                save_cache(cache)
                print(f"  {done}/{len(chunk)} (saved)", flush=True)
    except FTimeout:
        print(f"  deadline hit at {done}/{len(chunk)} — killing stalled fetches", flush=True)

    # Sites we didn't get to are simply crawled in the next batch. Marking them
    # "blocked" here is what used to remove healthy businesses from outreach:
    # they had never been requested at all. A site that really hangs is caught
    # per-site by crawl_business, so it can't starve the rest of the batch.
    unfinished = [b for b in chunk if b["place_id"] not in cache]
    for fut in futs:
        fut.cancel()
    if unfinished and done == 0:
        # Nothing finished in a whole batch window: quarantine rather than loop.
        for b in unfinished:
            cache[b["place_id"]] = E.SiteFindings(
                place_id=b["place_id"], crawl_error="blocked_crawl_hang")
        print(f"  {len(unfinished)} site(s) quarantined after a batch with no progress", flush=True)
    elif unfinished:
        print(f"  {len(unfinished)} site(s) carried over to the next batch", flush=True)
    save_cache(cache)

    # Kill the stalled children rather than joining them; a normal shutdown
    # would block on exactly the sockets we just gave up on.
    for proc in list(getattr(ex, "_processes", {}).values()):
        try:
            proc.kill()
        except Exception:
            pass
    ex.shutdown(wait=False, cancel_futures=True)

    remaining = sum(1 for b in businesses if b["place_id"] not in cache)
    print(f"done. {remaining} sites still to crawl.")

    store, run_id = active_run_store()
    if store is not None:
        crawled = sum(
            1 for b in businesses
            if b.get("website_url") and b["place_id"] in cache
        )
        store.update_run_progress(
            run_id,
            stage="crawl" if remaining else "psi",
            websites_crawled=crawled,
            crawl_finished_at=(
                datetime.now(timezone.utc) if remaining == 0 else None
            ),
        )


def cmd_psi(businesses, cache, batch: int) -> None:
    """PageSpeed only the leads where the number could change the pitch.

    Two-pass by design: everything is provisionally scored without PSI, then we
    spend the slow, rate-limited PSI budget on the highest-scoring reachable
    sites. A business with no website and no reviews doesn't need a Lighthouse
    score to be obviously worth calling.
    """
    scored, _ = S.score_all(businesses, cache)
    by_id = {b["place_id"]: b for b in businesses}
    order = [s.place_id for s in scored]

    todo = []
    for pid in order:
        f = cache.get(pid)
        if not f or not f.is_reachable:
            continue
        if f.psi_performance is not None:
            continue
        todo.append(by_id[pid])

    if not todo:
        print("psi complete — nothing left")

        run_store, run_id = active_run_store(required=True)

        psi_completed = sum(
            1 for f in cache.values()
            if getattr(f, "psi_performance", None) is not None
        )

        run_store.update_run_progress(
            run_id,
            stage="finalize",
            psi_completed=psi_completed,
            psi_finished_at=datetime.now(timezone.utc),
        )
        return
    chunk = todo[:batch]
    print(f"running PageSpeed on top {len(chunk)} of {len(todo)} candidates...")

    run_store, run_id = active_run_store()
    if run_store is not None:
        run_store.update_run_progress(run_id, stage="psi")

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {
            ex.submit(E.run_psi,
                      cache[b["place_id"]].resolved_url or b["website_url"],
                      C.GOOGLE_API_KEY): b
            for b in chunk
        }
        done = 0
        for fut in as_completed(futs):
            b = futs[fut]
            try:
                E.apply_psi(cache[b["place_id"]], fut.result())
            except Exception as e:
                print(f"  psi fail {b.get('name')}: {e}")
            done += 1

            if run_store is not None:
                run_store.increment_run_counters(run_id, psi_calls=1)

            # Save as we go. PageSpeed is slow enough that a batch can hit the
            # execution timeout, and a save-at-the-end would throw away every
            # result in the batch. Incremental saves make the work durable.
            if done % 4 == 0:
                save_cache(cache)
                print(f"  {done}/{len(chunk)} (saved)")
    save_cache(cache)

    remaining = len(todo) - len(chunk)

    print(
        f"done. {remaining} candidates remain "
        "(stop whenever)."
    )

    if run_store is not None:
        psi_completed = sum(
            1 for f in cache.values()
            if getattr(f, "psi_performance", None) is not None
        )

        progress = {
            "stage": "finalize" if remaining == 0 else "psi",
            "psi_completed": psi_completed,
        }

        if remaining == 0:
            progress["psi_finished_at"] = datetime.now(
                timezone.utc
            )

        run_store.update_run_progress(
            run_id,
            **progress,
        )


def cmd_finalize(businesses, cache, args) -> None:
    scored, baselines = S.score_all(businesses, cache)
    summarize(scored, businesses, baselines)
    export_csv(businesses, cache, scored, args.out)
    print(f"\nCSV -> {args.out}")

    if args.no_db:
        return
    from run_state import clear_current_run

    store, run_id = active_run_store(required=True)

    crawled = sum(
        1 for b in businesses
        if b.get("website_url") and b["place_id"] in cache
    )
    psi_completed = sum(
        1 for f in cache.values()
        if getattr(f, "psi_performance", None) is not None
    )

    store.update_run_progress(
        run_id,
        stage="finalize",
        websites_crawled=crawled,
        psi_completed=psi_completed,
    )

    store.save_businesses(businesses, run_id)
    store.save_enrichment(cache)
    store.save_baselines(baselines, run_id)
    store.save_scores(scored, run_id)
    store.finish_run(run_id)

    clear_current_run(run_id)
    print(f"saved to PostgreSQL. run_id={run_id}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["crawl", "psi", "status", "finalize"])
    ap.add_argument("--batch", type=int, default=60)
    ap.add_argument("--no-db", action="store_true")
    ap.add_argument("--out", default="leads.csv")
    args = ap.parse_args()

    businesses = load_businesses()
    cache = load_cache()

    if args.command == "status":
        cmd_status(businesses, cache)
    elif args.command == "crawl":
        active_run_store(required=True)
        cmd_crawl(businesses, cache, args.batch)
        cmd_status(businesses, cache)
    elif args.command == "psi":
        active_run_store(required=True)
        cmd_psi(businesses, cache, args.batch)
    elif args.command == "finalize":
        cmd_finalize(businesses, cache, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
