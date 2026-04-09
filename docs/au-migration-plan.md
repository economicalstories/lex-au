# AU Migration Plan

Adaptation of `lex-au` for Australian federal legislation from `legislation.gov.au`.

Two independent workstreams, each in a separate session:

- **Plan A** — Python ingestion pipeline (local laptop + CUDA → Cloudflare Vectorize)
- **Plan B** — Cloudflare Worker MCP server (Vectorize + Workers AI → MCP endpoint)

---

## Architecture Overview

```
┌─────────────────────────────────────┐
│  YOUR LAPTOP (ingestion, Plan A)    │
│                                     │
│  src/lex_au/                        │
│  ├── scraper.py                     │
│  │   └── scrapes legislation.gov.au │
│  ├── parser.py                      │
│  │   └── AU CLML XML → Pydantic     │
│  ├── embeddings.py                  │
│  │   └── BAAI/bge-large-en-v1.5    │
│  │       sentence-transformers+CUDA │
│  └── vectorize_client.py            │
│      └── REST upsert → Vectorize    │
└───────────────┬─────────────────────┘
                │ vectors + metadata
                ▼
┌─────────────────────────────────────┐
│  CLOUDFLARE                         │
│                                     │
│  Vectorize: au-legislation          │
│  Vectorize: au-legislation-section  │
│                                     │
│  Worker: workers/lex-au/ (Plan B)   │
│  ├── /mcp           MCP endpoint    │
│  ├── /legislation/* REST search     │
│  └── /proxy/*       gov.au proxy    │
└───────────────┬─────────────────────┘
                │ MCP over HTTPS
                ▼
┌─────────────────────────────────────┐
│  CLAUDE / any MCP client            │
│  .mcp.json → Worker URL             │
└─────────────────────────────────────┘
```

**Critical constraint**: embedding model must match at ingest and query time:
- Ingest (Plan A): `BAAI/bge-large-en-v1.5` via `sentence-transformers`
- Query (Plan B): `@cf/baai/bge-large-en-v1.5` via Workers AI

---

## Plan A: AU Ingestion Pipeline

### New package: `src/lex_au/`

```
src/lex_au/
├── __init__.py
├── settings.py              # AU types, Vectorize config, year ranges
├── models.py                # AULegislation, AULegislationSection Pydantic models
├── core/
│   ├── __init__.py
│   ├── embeddings.py        # sentence-transformers + CUDA (replaces Azure OpenAI)
│   ├── vectorize_client.py  # Cloudflare Vectorize REST API (replaces Qdrant)
│   └── http.py              # HTTP client (adapted from src/lex/core/http.py)
├── legislation/
│   ├── __init__.py
│   ├── scraper.py           # Scraper for legislation.gov.au
│   ├── pipeline.py          # Orchestration: scrape → parse → embed → upsert
│   └── parser/
│       ├── __init__.py
│       └── xml_parser.py    # AU CLML XML parser (adapted from UK parser)
└── ingest/
    ├── __init__.py
    ├── __main__.py          # CLI entry point
    └── orchestrator.py      # Batch pipeline runner
```

### Key design decisions

**Embeddings** — replace `src/lex/core/embeddings.py` (Azure OpenAI) with:
```python
from sentence_transformers import SentenceTransformer
import torch

def get_model():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    return SentenceTransformer("BAAI/bge-large-en-v1.5", device=device)

def embed_batch(texts: list[str]) -> list[list[float]]:
    return get_model().encode(texts, normalize_embeddings=True, batch_size=64).tolist()
```

**Sparse vectors** — Vectorize doesn't compute BM25 server-side (unlike Qdrant).
Use a hashing-trick TF tokeniser client-side. Token indices: `djb2_hash(token) % 30_000`.
The **same hashing logic must be replicated in TypeScript** in Plan B so query vectors
match document vectors.

**Storage split** — Vectorize metadata is limited to 10KB per vector, so full text is excluded:
| Store | What |
|---|---|
| Vectorize vector | 1024-dim dense + sparse indices/values + filterable metadata |
| Vectorize metadata | `id`, `title`, `legislation_id`, `type`, `year`, `provision_type` (no `text`) |

Full text retrieval uses the `/proxy/:id` endpoint in Plan B to fetch live from legislation.gov.au,
or can be fetched directly by the client.

**Vectorize REST upsert** (NDJSON, 1000 vectors/call max):
```
POST https://api.cloudflare.com/client/v4/accounts/{account_id}/vectorize/v2/indexes/{name}/upsert
Content-Type: application/x-ndjson
{"id":"uuid","values":[...],"sparse_values":{"indices":[...],"values":[...]},"metadata":{...}}
```

### AU Legislation types

```python
class AULegislationType(str, Enum):
    ACT = "act"     # C-series: C2022A00007
    LI  = "li"      # F-series legislative instruments: F2022L00001
    NI  = "ni"      # F-series notifiable instruments: F2022N00001
```

### Scraper — ⚠️ Requires API investigation

`legislation.gov.au` doesn't have the same well-documented XML API as `legislation.gov.uk`.
Requires reverse-engineering during implementation. Known patterns to investigate:
- `GET /Browse/Results/ByTitle/Acts/Current` — browse listing
- `GET /Details/{series_id}` — series detail page
- `GET /Details/{id}/Download` or `/Download/Legislation` — XML download
- Atom/RSS feeds at browse endpoints

Structure mirrors `src/lex/legislation/scraper.py`:
1. `discover_series_ids(type, year)` → yields series IDs
2. `fetch_xml(series_id)` → returns raw XML bytes
3. Reuse `HttpClient` from `src/lex/core/http.py` (remove HTTP 436 handling, keep 429)

### Parser — AU CLML

Australian legislation uses CLML (same family as UK). Key differences to verify from sample XML:
- Metadata namespace: UK uses `ukm:Year`, `ukm:Number`, `ukm:EnactmentDate` — AU equivalents TBC
- Extent mapping: replace E/W/S/N.I. with `AUJurisdiction.FEDERAL` for all federal Acts
- URI structure: AU uses `C2022A00007` / `F2022L00001` style, not `ukpga/2022/7` style

The section-level parsing (`Body`, `P1`, `Schedules` CLML elements) should transfer largely
unchanged — these are standard CLML constructs.

### CLI

```bash
uv run -m lex_au.ingest \
  --mode full \
  --type act li ni \
  --year 2020 2021 2022-2024 \
  --batch-size 50
```

Modes: `full` (all time), `recent` (current + last year), `setup` (create Vectorize indexes).

### New pyproject.toml dependencies

```toml
[dependency-groups]
lex-au = [
    "sentence-transformers>=3.0.0",
    "torch>=2.3.0",
    "rank-bm25>=0.2.2",
    "httpx>=0.27.0",
]
```

---

## Plan B: Cloudflare Worker MCP Server

### New package: `workers/lex-au/`

```
workers/lex-au/
├── wrangler.toml
├── package.json
├── tsconfig.json
└── src/
    ├── index.ts              # Worker entrypoint + Hono app wiring
    ├── env.ts                # Cloudflare bindings interface
    ├── types.ts              # TypeScript interfaces (mirror AU Pydantic models)
    ├── vectorize/
    │   ├── client.ts         # Workers AI embedding + Vectorize query helpers
    │   ├── sparse.ts         # BM25 hashing (must match Python tokeniser exactly)
    │   └── fusion.ts         # Manual score merging (approximates DBSF)
    ├── routes/
    │   ├── legislation.ts    # REST endpoints: /search, /section/search, /lookup, /text
    │   └── proxy.ts          # Proxy to legislation.gov.au with 24h cache
    ├── mcp/
    │   ├── server.ts         # JSON-RPC MCP protocol handler
    │   └── tools.ts          # 5 MCP tool definitions + dispatch
    └── middleware/
        └── rateLimit.ts      # Cloudflare native rate limiting
```

### wrangler.toml

```toml
name = "lex-au"
main = "src/index.ts"
compatibility_date = "2025-04-01"
compatibility_flags = ["nodejs_compat"]

[[vectorize]]
binding = "LEGISLATION_INDEX"
index_name = "au-legislation"

[[vectorize]]
binding = "LEGISLATION_SECTION_INDEX"
index_name = "au-legislation-section"

[[ai]]
binding = "AI"

[[unsafe.bindings]]
name = "RATE_LIMITER"
type = "ratelimit"
namespace_id = "1001"
simple = { limit = 100, period = 60 }
```

### Search logic

Query-time flow in `src/vectorize/client.ts`:
1. Embed query: `env.AI.run("@cf/baai/bge-large-en-v1.5", { text: [query] })`
2. Compute sparse vector via same `djb2Hash % 30_000` tokeniser as Plan A
3. Query `LEGISLATION_SECTION_INDEX` (dense + sparse, run in parallel if sparse bindings available)
4. Fuse scores with min-max normalisation + weighted sum (dense×3, sparse×0.8)
5. For act-level search: group sections by `legislation_id`, merge title match boost (+0.3×)
6. Batch fetch metadata from Vectorize `getByIds()`

**Fallback**: If Vectorize sparse vector queries are not yet supported in Worker bindings,
use dense-only. Quality remains good for this corpus size.

### MCP tools (5 tools)

| Tool | Description |
|---|---|
| `search_for_au_legislation_acts` | Semantic search across Acts and LIs by topic |
| `search_for_au_legislation_sections` | Search within sections; filter by `legislation_id` |
| `lookup_au_legislation` | Get specific Act/LI by type + year + number |
| `get_au_legislation_sections` | All sections of a specific Act |
| `get_au_legislation_full_text` | Concatenated full text of an Act |

MCP protocol: JSON-RPC 2.0 over POST `/mcp`. Handles `initialize`, `tools/list`, `tools/call`.
Consider using `@modelcontextprotocol/sdk` if it compiles for Workers (no Node.js dependencies).

### `.mcp.json` (update repo root)

```json
{
  "mcpServers": {
    "lex-au": {
      "type": "http",
      "url": "https://lex-au.YOUR-SUBDOMAIN.workers.dev/mcp"
    }
  }
}
```

---

## Implementation Sequence

### Plan A
1. Research `legislation.gov.au` API (browse with DevTools, obtain sample AU Act XML)
2. `src/lex_au/models.py` — AU types, AULegislation, AULegislationSection
3. `src/lex_au/settings.py` — AU config + Vectorize settings
4. `src/lex_au/core/embeddings.py` — sentence-transformers + CUDA + BM25 hashing
5. `src/lex_au/core/vectorize_client.py` — REST upsert client
6. `src/lex_au/legislation/scraper.py` — AU scraper (based on Step 1 findings)
7. `src/lex_au/legislation/parser/xml_parser.py` — AU CLML parser
8. `src/lex_au/legislation/pipeline.py` + `src/lex_au/ingest/` — orchestration + CLI
9. Test run: `--type act --year 2022 --limit 10`

### Plan B
1. Scaffold `workers/lex-au/` with `wrangler`, install Hono
2. `src/env.ts`, `src/types.ts`
3. `src/vectorize/sparse.ts` — tokeniser (verify matches Python output)
4. `src/vectorize/client.ts` — Workers AI embed + Vectorize query (dense-only first)
5. `src/vectorize/fusion.ts` — score merging
6. `src/routes/legislation.ts` — all search + lookup endpoints
7. `src/routes/proxy.ts` — legislation.gov.au proxy
8. `src/mcp/tools.ts` + `src/mcp/server.ts` — MCP protocol
9. `src/middleware/rateLimit.ts`
10. Deploy + test with Claude Code via `.mcp.json`

---

## Key Risks

| Risk | Mitigation |
|---|---|
| `legislation.gov.au` XML API undocumented | Reverse-engineer from browser DevTools; fallback to bulk XML download packages |
| AU CLML namespace differences | Obtain sample XML before writing parser |
| Vectorize sparse vector Worker binding unavailable | Fall back to dense-only search for MVP |
| BM25 hash mismatch between Python and TypeScript | Write cross-language test with 10 sample texts |
| Vectorize `getByIds()` unavailable | Use `$in` metadata filter query as fallback |

---

## Reference Files

These existing files are the direct templates for the AU equivalents:

| AU file | Template from |
|---|---|
| `src/lex_au/core/embeddings.py` | `src/lex/core/embeddings.py` (replace Azure OAI with sentence-transformers) |
| `src/lex_au/legislation/scraper.py` | `src/lex/legislation/scraper.py` (rewrite URL patterns) |
| `src/lex_au/legislation/parser/xml_parser.py` | `src/lex/legislation/parser/xml_parser.py` (update metadata elements) |
| `src/lex_au/ingest/orchestrator.py` | `src/lex/ingest/orchestrator.py` (replace Qdrant with Vectorize client) |
| `workers/lex-au/src/routes/legislation.ts` | `src/backend/legislation/search.py` (port two-tier search to TypeScript) |
| `workers/lex-au/src/vectorize/fusion.ts` | DBSF logic in `src/backend/legislation/search.py` |
