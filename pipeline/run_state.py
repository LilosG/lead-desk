"""Durable pointer to the active staged Lead Desk run.

PostgreSQL is authoritative for run state and telemetry. This file contains
only the UUID/context required for separate CLI invocations to address the
same database run.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

STATE_FILE = Path(__file__).with_name(".current_run.json")


def save_current_run(
    run_id: str,
    geo_label: str,
    verticals: list[str],
    *,
    replace: bool = False,
) -> None:
    existing = load_current_run()

    if existing and not replace:
        existing_run_id = existing.get("run_id")
        raise RuntimeError(
            "active run pointer already exists "
            f"(run_id={existing_run_id}); "
            "refusing to overwrite pipeline/.current_run.json"
        )

    payload = {
        "run_id": str(run_id),
        "geo_label": geo_label,
        "verticals": sorted(verticals),
    }

    fd, tmp = tempfile.mkstemp(
        prefix=".current_run.",
        suffix=".tmp",
        dir=STATE_FILE.parent,
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_FILE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_current_run() -> dict | None:
    if not STATE_FILE.exists():
        return None
    with STATE_FILE.open() as f:
        return json.load(f)


def clear_current_run(expected_run_id: str | None = None) -> None:
    state = load_current_run()

    if not state:
        return

    if expected_run_id and state.get("run_id") != str(expected_run_id):
        raise RuntimeError(
            "refusing to clear current-run state: run_id does not match"
        )

    STATE_FILE.unlink()
