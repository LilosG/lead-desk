#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

import run_state


def main() -> int:
    original = run_state.STATE_FILE

    try:
        with tempfile.TemporaryDirectory() as tmp:
            run_state.STATE_FILE = (
                Path(tmp) / ".current_run.json"
            )

            assert run_state.load_current_run() is None

            run_state.save_current_run(
                "run-1",
                "Test Market",
                ["electrician"],
            )

            state = run_state.load_current_run()

            assert state is not None
            assert state["run_id"] == "run-1"

            try:
                run_state.save_current_run(
                    "run-2",
                    "Test Market",
                    ["electrician"],
                )
            except RuntimeError:
                pass
            else:
                raise AssertionError(
                    "pointer overwrite was not rejected"
                )

            try:
                run_state.clear_current_run("wrong-run")
            except RuntimeError:
                pass
            else:
                raise AssertionError(
                    "mismatched clear was not rejected"
                )

            run_state.clear_current_run("run-1")

            assert run_state.load_current_run() is None

        print("PASS pointer create")
        print("PASS pointer overwrite rejected")
        print("PASS mismatched clear rejected")
        print("PASS pointer clear")
        print("ALL CHECKS PASSED")

        return 0
    finally:
        run_state.STATE_FILE = original


if __name__ == "__main__":
    raise SystemExit(main())
