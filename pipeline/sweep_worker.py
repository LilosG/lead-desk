#!/usr/bin/env python3

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from run_state import load_current_run
from store import PostgresStore


ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "bin" / "python"


class SweepCancelled(RuntimeError):
    pass


def execution_enabled() -> bool:
    return os.getenv(
        "SWEEP_EXECUTION_ENABLED",
        "false",
    ).lower() in {"1", "true", "yes", "on"}


def connect():
    return psycopg.connect(
        os.environ["DATABASE_URL"],
        row_factory=dict_row,
    )


def claim_next_job() -> dict[str, Any] | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select *
                from sweep_jobs
                where status = 'queued'
                  and cancel_requested = false
                order by created_at
                for update skip locked
                limit 1
                """
            )

            job = cur.fetchone()

            if not job:
                return None

            cur.execute(
                """
                update sweep_jobs
                set
                    status = 'running',
                    stage = 'discovery',
                    worker_pid = %s,
                    started_at = now(),
                    updated_at = now()
                where id = %s
                returning *
                """,
                (os.getpid(), job["id"]),
            )

            return cur.fetchone()


def update_job(job_id, **fields) -> None:
    allowed = {
        "run_id",
        "status",
        "stage",
        "cancel_requested",
        "child_pid",
        "error_message",
    }

    unknown = set(fields) - allowed

    if unknown:
        raise ValueError(
            f"unsupported sweep job fields: {sorted(unknown)}"
        )

    if not fields:
        return

    assignments = ", ".join(
        f"{key} = %s"
        for key in fields
    )

    params = list(fields.values()) + [job_id]

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                update sweep_jobs
                set
                    {assignments},
                    updated_at = now()
                where id = %s
                """,
                params,
            )


def finish_job(
    job_id,
    *,
    status: str,
    stage: str,
    error: str | None = None,
) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update sweep_jobs
                set
                    status = %s,
                    stage = %s,
                    error_message = %s,
                    child_pid = null,
                    finished_at = now(),
                    updated_at = now()
                where id = %s
                """,
                (status, stage, error, job_id),
            )


def cancel_requested(job_id) -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select cancel_requested
                from sweep_jobs
                where id = %s
                """,
                (job_id,),
            )

            row = cur.fetchone()

            return bool(
                row and row["cancel_requested"]
            )


def run_command(
    job_id,
    stage: str,
    command: list[str],
) -> None:
    if cancel_requested(job_id):
        raise SweepCancelled()

    update_job(
        job_id,
        stage=stage,
    )

    proc = subprocess.Popen(
        command,
        cwd=ROOT,
        env=os.environ.copy(),
        start_new_session=True,
    )

    update_job(
        job_id,
        child_pid=proc.pid,
    )

    try:
        while proc.poll() is None:
            if cancel_requested(job_id):
                try:
                    os.killpg(
                        proc.pid,
                        signal.SIGTERM,
                    )
                except ProcessLookupError:
                    pass

                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(
                            proc.pid,
                            signal.SIGKILL,
                        )
                    except ProcessLookupError:
                        pass

                raise SweepCancelled()

            time.sleep(1)

        if proc.returncode != 0:
            raise RuntimeError(
                f"{stage} exited with code {proc.returncode}"
            )

    finally:
        update_job(
            job_id,
            child_pid=None,
        )


def get_active_run() -> dict[str, Any] | None:
    return PostgresStore().get_active_run()


def attach_run(job_id) -> str:
    state = load_current_run()

    if not state:
        raise RuntimeError(
            "Discovery completed without an active run pointer."
        )

    run_id = str(state["run_id"])

    active = get_active_run()

    if not active:
        raise RuntimeError(
            "Discovery completed without an active database run."
        )

    if str(active["id"]) != run_id:
        raise RuntimeError(
            "Run pointer and active database run do not match."
        )

    update_job(
        job_id,
        run_id=run_id,
    )

    return run_id


def abandon_active(reason: str) -> None:
    active = get_active_run()

    if not active:
        return

    subprocess.run(
        [
            str(PYTHON),
            str(ROOT / "pipeline" / "runctl.py"),
            "abandon",
            "--reason",
            reason,
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        check=False,
    )


def execute_job(job: dict[str, Any]) -> None:
    job_id = job["id"]

    if not execution_enabled():
        raise RuntimeError(
            "Sweep execution disabled by SWEEP_EXECUTION_ENABLED."
        )

    verticals = list(job["verticals"])
    cities = list(job["cities"] or [])

    discover = [
        str(PYTHON),
        str(ROOT / "pipeline" / "discover.py"),
        "--verticals",
        *verticals,
        "--out",
        "discovered.json",
    ]

    if cities:
        discover.extend([
            "--cities",
            *cities,
        ])

    if job["use_grid"]:
        discover.append("--grid")

    if job["merge_results"]:
        discover.append("--merge")

    run_command(
        job_id,
        "discovery",
        discover,
    )

    run_id = attach_run(job_id)

    # Crawl at least once, then continue in bounded batches
    # until pipeline state advances out of crawl.
    while True:
        run_command(
            job_id,
            "crawl",
            [
                str(PYTHON),
                str(ROOT / "pipeline" / "pipeline.py"),
                "crawl",
                "--batch",
                str(job["crawl_batch"]),
            ],
        )

        active = get_active_run()

        if not active:
            raise RuntimeError(
                "Active run disappeared during crawl."
            )

        if str(active["id"]) != run_id:
            raise RuntimeError(
                "Active run changed during crawl."
            )

        if active["stage"] != "crawl":
            break

    if cancel_requested(job_id):
        raise SweepCancelled()

    # Preserve the original Lead Desk PSI budget:
    # one bounded batch per sweep.
    run_command(
        job_id,
        "psi",
        [
            str(PYTHON),
            str(ROOT / "pipeline" / "pipeline.py"),
            "psi",
            "--batch",
            str(job["psi_batch"]),
        ],
    )

    active = get_active_run()

    if not active:
        raise RuntimeError(
            "Active run disappeared after PSI."
        )

    if str(active["id"]) != run_id:
        raise RuntimeError(
            "Active run changed after PSI."
        )

    PostgresStore().update_run_progress(
        run_id,
        stage="finalize",
        psi_finished_at=datetime.now(
            timezone.utc
        ),
    )

    run_command(
        job_id,
        "finalize",
        [
            str(PYTHON),
            str(ROOT / "pipeline" / "pipeline.py"),
            "finalize",
            "--out",
            "leads.csv",
        ],
    )


def process(job: dict[str, Any]) -> None:
    job_id = job["id"]

    try:
        execute_job(job)

    except SweepCancelled:
        abandon_active(
            "Sweep cancelled by operator"
        )

        finish_job(
            job_id,
            status="cancelled",
            stage="cancelled",
        )

    except Exception as exc:
        abandon_active(
            f"Sweep worker failure: {exc}"
        )

        finish_job(
            job_id,
            status="failed",
            stage="failed",
            error=str(exc),
        )

        print(
            f"job {job_id} failed: {exc}",
            file=sys.stderr,
        )

    else:
        finish_job(
            job_id,
            status="completed",
            stage="completed",
        )


def main() -> int:
    print(
        "Lead Desk sweep worker starting",
        flush=True,
    )

    if not execution_enabled():
        print(
            "Sweep execution disabled; worker will remain idle.",
            flush=True,
        )

        while True:
            time.sleep(3600)

    while True:
        job = claim_next_job()

        if not job:
            time.sleep(2)
            continue

        print(
            f"processing sweep job {job['id']}",
            flush=True,
        )

        process(job)


if __name__ == "__main__":
    raise SystemExit(main())
