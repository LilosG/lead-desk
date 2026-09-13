#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
from pathlib import Path

import psycopg


ROOT = Path(__file__).resolve().parent
MIGRATIONS_DIR = ROOT / "migrations"

MIGRATION_RE = re.compile(r"^(\d{3})[^/]*\.sql$")


def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise SystemExit("DATABASE_URL is not set")
    return value


def migration_files() -> list[tuple[str, Path]]:
    migrations: list[tuple[str, Path]] = []

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = MIGRATION_RE.match(path.name)
        if not match:
            continue

        migrations.append((match.group(1), path))

    versions = [version for version, _ in migrations]

    if len(versions) != len(set(versions)):
        raise SystemExit("duplicate migration version detected")

    return migrations


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_ledger(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        create table if not exists schema_migrations (
            version text primary key,
            filename text not null,
            checksum_sha256 text not null,
            applied_at timestamptz not null default now()
        )
        """
    )


def applied(conn: psycopg.Connection) -> dict[str, tuple[str, str]]:
    rows = conn.execute(
        """
        select version, filename, checksum_sha256
        from schema_migrations
        order by version
        """
    ).fetchall()

    return {
        str(version): (str(filename), str(checksum))
        for version, filename, checksum in rows
    }


def validate_applied(
    known: list[tuple[str, Path]],
    existing: dict[str, tuple[str, str]],
) -> None:
    known_map = {version: path for version, path in known}

    for version, (filename, recorded_checksum) in existing.items():
        path = known_map.get(version)

        if path is None:
            raise RuntimeError(
                f"database contains unknown migration version {version}"
            )

        actual_checksum = checksum(path)

        if filename != path.name:
            raise RuntimeError(
                f"migration {version} filename mismatch: "
                f"database={filename!r} filesystem={path.name!r}"
            )

        if recorded_checksum != actual_checksum:
            raise RuntimeError(
                f"migration {version} checksum mismatch; "
                "an applied migration file has been modified"
            )


def show_status(conn: psycopg.Connection) -> None:
    known = migration_files()
    existing = applied(conn)

    validate_applied(known, existing)

    for version, path in known:
        state = "applied" if version in existing else "pending"
        print(f"{version}  {state:<7}  {path.name}")


def baseline_existing(conn: psycopg.Connection) -> None:
    known = migration_files()
    existing = applied(conn)

    if existing:
        raise RuntimeError(
            "schema_migrations is not empty; refusing to baseline"
        )

    if not known:
        raise RuntimeError("no migration files found")

    for version, path in known:
        conn.execute(
            """
            insert into schema_migrations (
                version,
                filename,
                checksum_sha256
            )
            values (%s, %s, %s)
            """,
            (version, path.name, checksum(path)),
        )

    print(
        "Baselined existing database through "
        f"migration {known[-1][0]}"
    )


def migrate(conn: psycopg.Connection) -> None:
    known = migration_files()
    existing = applied(conn)

    validate_applied(known, existing)

    pending = [
        (version, path)
        for version, path in known
        if version not in existing
    ]

    if not pending:
        print("Database is up to date")
        return

    for version, path in pending:
        sql = path.read_text()

        print(f"Applying {version}: {path.name}")

        with conn.transaction():
            conn.execute(sql)
            conn.execute(
                """
                insert into schema_migrations (
                    version,
                    filename,
                    checksum_sha256
                )
                values (%s, %s, %s)
                """,
                (version, path.name, checksum(path)),
            )

    print(f"Applied {len(pending)} migration(s)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["status", "baseline-existing", "migrate"],
    )
    args = parser.parse_args()

    with psycopg.connect(database_url(), autocommit=True) as conn:
        ensure_ledger(conn)

        if args.command == "status":
            show_status(conn)
        elif args.command == "baseline-existing":
            baseline_existing(conn)
        elif args.command == "migrate":
            migrate(conn)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
