#!/usr/bin/env bash
set -euo pipefail

# Idempotent setup for Cloudflare Vectorize resources used by workers/lex-au.
# Requires: authenticated Wrangler session (`npx wrangler@latest whoami`).

DIMENSIONS="${DIMENSIONS:-1024}"
METRIC="${METRIC:-cosine}"

run_wrangler() {
  npx wrangler@latest "$@"
}

run_or_skip_if_exists() {
  local description="$1"
  shift

  local output
  if output="$(run_wrangler "$@" 2>&1)"; then
    echo "✅ ${description}"
    return 0
  fi

  if [[ "$output" == *"already exists"* ]]; then
    echo "↩️  ${description} (already exists)"
    return 0
  fi

  echo "❌ Failed: ${description}" >&2
  echo "$output" >&2
  return 1
}

echo "==> Creating Vectorize indexes (safe to re-run)"
run_or_skip_if_exists \
  "Vectorize index au-legislation" \
  vectorize create au-legislation --dimensions="${DIMENSIONS}" --metric="${METRIC}"

run_or_skip_if_exists \
  "Vectorize index au-legislation-section" \
  vectorize create au-legislation-section --dimensions="${DIMENSIONS}" --metric="${METRIC}"

echo "==> Creating metadata indexes (safe to re-run)"
run_or_skip_if_exists \
  "Metadata index au-legislation:type (string)" \
  vectorize create-metadata-index au-legislation --property-name=type --type=string

run_or_skip_if_exists \
  "Metadata index au-legislation:year (number)" \
  vectorize create-metadata-index au-legislation --property-name=year --type=number

run_or_skip_if_exists \
  "Metadata index au-legislation-section:legislation_id (string)" \
  vectorize create-metadata-index au-legislation-section --property-name=legislation_id --type=string

run_or_skip_if_exists \
  "Metadata index au-legislation-section:type (string)" \
  vectorize create-metadata-index au-legislation-section --property-name=type --type=string

run_or_skip_if_exists \
  "Metadata index au-legislation-section:year (number)" \
  vectorize create-metadata-index au-legislation-section --property-name=year --type=number

run_or_skip_if_exists \
  "Metadata index au-legislation-section:provision_type (string)" \
  vectorize create-metadata-index au-legislation-section --property-name=provision_type --type=string

echo "==> Done"
echo "Run this to verify: npx wrangler@latest vectorize list"
