#!/usr/bin/env python3
"""Operator controls for Lead Desk staged runs.

PostgreSQL is authoritative. pipeline/.current_run.json is only the
durable pointer used by separate CLI stages.
"""

from __future__ import annotations

import argparse
import json

from run_state import (
    clear_current_run,
    load_current_run,
    save_current_run,
)
from store import PostgresStore


def store_or_die() -> PostgresStore:
    store = PostgresStore()

    if not store.ping():
        raise SystemExit("PostgreSQL unavailable")

    return store


def status() -> int:
    store = store_or_die()

    pointer = load_current_run()
    active = store.get_active_run()

    print("pointer:")
    print(
        json.dumps(pointer, indent=2, default=str)
        if pointer
        else "  none"
    )

    print("database active run:")
    print(
        json.dumps(active, indent=2, default=str)
        if active
        else "  none"
    )

    if not pointer and not active:
        print("state: idle")
        return 0

    if pointer and active:
        if str(pointer.get("run_id")) == str(active["id"]):
            print("state: aligned")
            return 0

        print("state: INCONSISTENT — run IDs differ")
        return 2

    if pointer and not active:
        print("state: INCONSISTENT — stale pointer")
        return 2

    print("state: RECOVERABLE — active DB run has no pointer")
    return 2


def recover() -> int:
    store = store_or_die()

    pointer = load_current_run()
    active = store.get_active_run()

    if not active:
        if pointer:
            raise SystemExit(
                "cannot recover: pointer exists but PostgreSQL "
                "has no active run; use abandon to clear stale state"
            )

        print("nothing to recover")
        return 0

    run_id = str(active["id"])

    if pointer:
        pointer_id = str(pointer.get("run_id"))

        if pointer_id == run_id:
            print(f"already aligned: run_id={run_id}")
            return 0

        raise SystemExit(
            "cannot recover automatically: pointer run "
            f"{pointer_id} differs from database run {run_id}"
        )

    save_current_run(
        run_id,
        str(active["geo_label"]),
        list(active["verticals"] or []),
    )

    print(f"recovered pointer for run_id={run_id}")
    return 0


def abandon(reason: str, force: bool) -> int:
    store = store_or_die()

    pointer = load_current_run()
    active = store.get_active_run()

    if not pointer and not active:
        print("nothing to abandon")
        return 0

    pointer_id = (
        str(pointer.get("run_id"))
        if pointer
        else None
    )

    active_id = (
        str(active["id"])
        if active
        else None
    )

    if (
        pointer_id
        and active_id
        and pointer_id != active_id
        and not force
    ):
        raise SystemExit(
            "pointer and database run IDs differ; "
            "refusing to abandon inconsistent state without --force"
        )

    if active_id:
        store.abandon_run(active_id, reason)
        print(f"database run abandoned: {active_id}")

    if pointer:
        if active_id and pointer_id == active_id:
            clear_current_run(active_id)
        elif force:
            clear_current_run()
        elif not active_id:
            clear_current_run()

        print(f"pointer cleared: {pointer_id}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    sub.add_parser("status")
    sub.add_parser("recover")

    abandon_parser = sub.add_parser("abandon")
    abandon_parser.add_argument(
        "--reason",
        default="Operator abandoned staged run",
    )
    abandon_parser.add_argument(
        "--force",
        action="store_true",
    )

    args = parser.parse_args()

    if args.command == "status":
        return status()

    if args.command == "recover":
        return recover()

    if args.command == "abandon":
        return abandon(args.reason, args.force)

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
