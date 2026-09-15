#!/usr/bin/env python3
from __future__ import annotations

from discover import datetime, timezone


def main() -> int:
    stamp = datetime.now(timezone.utc)
    assert stamp.tzinfo is not None
    assert stamp.utcoffset() is not None
    print("PASS discovery lifecycle timestamp dependencies are available")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
