#!/usr/bin/env bash
# Copy an existing OPENAI_API_KEY from one of your other projects into Lead Desk's .env.
# Never prints the key. Usage: scripts/adopt_openai_key.sh [path/to/other/.env]
set -euo pipefail
cd "$(dirname "$0")/.."
TARGET="$PWD/.env"

if grep -qE '^OPENAI_API_KEY=.+' "$TARGET" 2>/dev/null; then
  echo "Lead Desk .env already has OPENAI_API_KEY. Nothing to do."
  exit 0
fi

if [ $# -ge 1 ]; then
  SOURCE="$1"
else
  mapfile -t FOUND < <(grep -lsE '^(export )?OPENAI_API_KEY=.+' \
    /home/mike/*/.env /home/mike/*/*/.env /home/mike/.env /etc/*/*.env /opt/*/.env 2>/dev/null | grep -v "^$TARGET$" || true)
  if [ "${#FOUND[@]}" -eq 0 ]; then
    echo "No OPENAI_API_KEY found in the usual .env spots. Run it with the path:"
    echo "  scripts/adopt_openai_key.sh /path/to/the/.env"
    echo "Or search: grep -rlE '^OPENAI_API_KEY=' /home/mike --include='.env*' 2>/dev/null"
    exit 1
  fi
  if [ "${#FOUND[@]}" -gt 1 ]; then
    echo "Found it in more than one place. Pick one and run:"
    printf '  scripts/adopt_openai_key.sh %s\n' "${FOUND[@]}"
    exit 1
  fi
  SOURCE="${FOUND[0]}"
fi

LINE=$(grep -E '^(export )?OPENAI_API_KEY=.+' "$SOURCE" | tail -1 | sed 's/^export //')
[ -n "$LINE" ] || { echo "No OPENAI_API_KEY in $SOURCE"; exit 1; }
printf '\n%s\n' "$LINE" >> "$TARGET"
echo "Copied OPENAI_API_KEY from $SOURCE into $TARGET (key not shown)."
