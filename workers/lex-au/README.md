# `workers/lex-au` deployment guide

This directory contains the Cloudflare Worker config for the AU migration (`wrangler.toml`).

## Source & terms of use

All substantive content served by this Worker is derived from the
[Federal Register of Legislation](https://www.legislation.gov.au) and is
reused under the
[legislation.gov.au Terms of Use](https://www.legislation.gov.au/terms-of-use).
The hosted landing page (`GET /`) surfaces this attribution and links back to
the original source — do not remove or alter it.

## What this worker config does

The included `wrangler.toml` wires the Worker to:

- `LEGISLATION_INDEX` → Vectorize index `au-legislation`
- `LEGISLATION_SECTION_INDEX` → Vectorize index `au-legislation-section`
- `AI` → Workers AI binding
- Rate limiting is configured in the Cloudflare dashboard (not committed in this repo)

The Worker exposes:

- `GET /` — mobile-optimised landing page with the MCP endpoint URL (derived
  from the request host, so there are no local-host callbacks), the copy-paste
  MCP client config, and the required `legislation.gov.au` attribution.
- `POST /mcp`, `GET /mcp` — MCP JSON-RPC / SSE endpoint.
- `POST /legislation/...` — REST endpoints for search, lookup and full text.
- `GET /proxy/:id` — cached proxy to legislation.gov.au.
- `GET /health` — health check; the response body advertises the source
  name, URL and terms-of-use URL.

The Worker also applies a few built-in public-edge guardrails:

- rate limiting on `/legislation/*`, `/proxy/*`, and `/mcp`
- request body limits on JSON endpoints
- clamped search pagination to keep queries bounded
- proxy path validation so only safe `legislation.gov.au` paths are fetched

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

## 2) Configure rate limiting in Cloudflare dashboard

To keep this repository public-safe, the `RATE_LIMITER` binding is **not** stored in
`wrangler.toml`.

In Cloudflare dashboard (Worker settings), add a native Rate Limiting binding:

- Binding name: `RATE_LIMITER`
- Type: `ratelimit`
- Rule: `limit = 100`, `period = 60` (or your preferred values)

## 3) Deploy the worker

From this directory:

```bash
npm install
npx wrangler@latest deploy
```

Wrangler will output your Worker URL. The canonical production deployment
for this repository is:

```text
https://lex-au.economicalstories.workers.dev
```

If you deploy to a different Cloudflare account the subdomain will differ —
the landing page at `/` always renders the correct MCP URL for whichever
deployment you hit, because it is derived from the incoming request host.

## 4) Connect MCP clients

Point your MCP client to the hosted endpoint (no local callbacks). For the
canonical production deployment use:

```text
https://lex-au.economicalstories.workers.dev/mcp
```

Or drop this block into your client's MCP config (Claude Desktop, Claude
Code, Cursor, VS Code, etc.):

```json
{
  "mcpServers": {
    "lex-au": {
      "type": "http",
      "url": "https://lex-au.economicalstories.workers.dev/mcp"
    }
  }
}
```

### Verify the MCP connection

Quick one-shot checks against the hosted endpoint (no local callbacks —
these hit the real Worker):

```bash
# Health (also advertises the legislation.gov.au source + terms of use URL)
curl -s https://lex-au.economicalstories.workers.dev/health | jq

# MCP initialize handshake
curl -sS https://lex-au.economicalstories.workers.dev/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize"}' | jq

# MCP tools/list — should return the 5 AU legislation tools
curl -sS https://lex-au.economicalstories.workers.dev/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | jq '.result.tools[].name'
```

If your Cloudflare account uses a different `workers.dev` subdomain,
substitute it in the URLs above (or just open the landing page in a
browser — the copy-paste block on it will already contain the correct URL).

## 5) Ingest data into Vectorize

After deployment, run the AU ingestion pipeline so vectors are upserted into:

- `au-legislation`
- `au-legislation-section`


## Troubleshooting: `Invalid TOML document` on deploy

If deploy fails with an error like:

```text
Invalid TOML document: trying to redefine an already defined table or value
.../workers/lex-au/wrangler.toml:...
```

check your AI binding stanza in `wrangler.toml`. It must be:

```toml
[ai]
binding = "AI"
```

Do **not** use `[[ai]]` here. `[[ai]]` defines an array-of-tables and causes Wrangler to fail parsing this config.

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
