#!/usr/bin/env bash
# Build a Lead Desk test database the way production evolved:
# base schema -> migrations 001-011 -> production view snapshot -> 012+.
# Usage: DATABASE_URL=postgresql://... scripts/build_test_db.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${DATABASE_URL:?DATABASE_URL is required}"
export PGOPTIONS="--client-min-messages=warning"

psql "$DATABASE_URL" -q -v ON_ERROR_STOP=1 -f sql/schema.sql >/dev/null
for f in sql/migrations/0*.sql; do
  v=$(basename "$f" | cut -c1-3)
  psql "$DATABASE_URL" -q -v ON_ERROR_STOP=1 -f "$f" >/dev/null
  if [ "$v" = "011" ]; then
    psql "$DATABASE_URL" -q -v ON_ERROR_STOP=1 -f sql/views.sql >/dev/null
  fi
done
echo "test database ready"
