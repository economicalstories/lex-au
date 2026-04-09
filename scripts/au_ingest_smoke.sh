#!/usr/bin/env bash
set -euo pipefail

# Run a tiny AU ingest smoke test with env loading and a safe default batch.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

# Backward-compatible fallback for the typo that may already exist in .env.
if [[ -z "${AU_MIN_REQUEST_INTERVAL_SECONDS:-}" && -n "${AU_MIN_REQUEST_INTERVA_SECONDS:-}" ]]; then
  export AU_MIN_REQUEST_INTERVAL_SECONDS="${AU_MIN_REQUEST_INTERVA_SECONDS}"
fi

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

PYTHON_BIN="${PYTHON_BIN:-python}"
exec "$PYTHON_BIN" -m lex_au.ingest --type act --year 2024 --limit 2 --batch-size 2 -v
