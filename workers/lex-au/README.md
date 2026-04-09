# `workers/lex-au` deployment guide

This directory contains the Cloudflare Worker config for the AU migration (`wrangler.toml`).

## What this worker config does

The included `wrangler.toml` wires the Worker to:

- `LEGISLATION_INDEX` → Vectorize index `au-legislation`
- `LEGISLATION_SECTION_INDEX` → Vectorize index `au-legislation-section`
- `AI` → Workers AI binding
- `RATE_LIMITER` → Cloudflare native rate limiter binding

## Prerequisites

- Node.js 20+
- Cloudflare account with Workers + Vectorize enabled
- Wrangler CLI (`npm i -g wrangler` or `npx wrangler@latest ...`)
- Authenticated CLI session (`wrangler login`)

## 1) Create Vectorize indexes

Fastest option (idempotent helper script):

```bash
./setup.sh
```

Manual option:

Run once:

```bash
npx wrangler@latest vectorize create au-legislation --dimensions=1024 --metric=cosine
npx wrangler@latest vectorize create au-legislation-section --dimensions=1024 --metric=cosine
```

Optional but recommended metadata indexes for filtering:

```bash
npx wrangler@latest vectorize create-metadata-index au-legislation --property-name=type --type=string
npx wrangler@latest vectorize create-metadata-index au-legislation --property-name=year --type=number

npx wrangler@latest vectorize create-metadata-index au-legislation-section --property-name=legislation_id --type=string
npx wrangler@latest vectorize create-metadata-index au-legislation-section --property-name=type --type=string
npx wrangler@latest vectorize create-metadata-index au-legislation-section --property-name=year --type=number
npx wrangler@latest vectorize create-metadata-index au-legislation-section --property-name=provision_type --type=string
```

## 2) Configure rate-limiter namespace ID

In `wrangler.toml`, update:

```toml
[[unsafe.bindings]]
name = "RATE_LIMITER"
type = "ratelimit"
namespace_id = "1001"  # replace this value
simple = { limit = 100, period = 60 }
```

Replace `1001` with your actual Cloudflare rate-limiter namespace ID.

## 3) Deploy the worker

From this directory:

```bash
npm install
npx wrangler@latest deploy
```

Wrangler will output your Worker URL, typically:

```text
https://lex-au.<your-subdomain>.workers.dev
```

## 4) Connect MCP clients

Point your MCP client to:

```text
https://lex-au.<your-subdomain>.workers.dev/mcp
```

## 5) Ingest data into Vectorize

After deployment, run the AU ingestion pipeline so vectors are upserted into:

- `au-legislation`
- `au-legislation-section`

## Common checks

```bash
# confirm auth/account
npx wrangler@latest whoami

# check indexes exist
npx wrangler@latest vectorize list

# tail worker logs
npx wrangler@latest tail
```

## Optional script configuration

`setup.sh` accepts:

- `DIMENSIONS` (default: `1024`)
- `METRIC` (default: `cosine`)

Example:

```bash
DIMENSIONS=1024 METRIC=cosine ./setup.sh
```
