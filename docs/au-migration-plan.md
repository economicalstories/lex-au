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
│  │   └── REST API at               │
│  │       api.prod.legislation.gov.au│
│  ├── parser/                        │
│  │   ├── epub_parser.py             │
│  │   │   └── EPUB HTML → sections  │
│  │   └── docx_parser.py            │
│  │       └── DOCX XML → full text  │
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
│   ├── scraper.py           # REST API client for api.prod.legislation.gov.au
│   ├── pipeline.py          # Orchestration: fetch → parse → embed → upsert
│   └── parser/
│       ├── __init__.py
│       ├── epub_parser.py   # EPUB HTML → AULegislationSection list (section-level)
│       └── docx_parser.py   # DOCX XML → full text string (legislation-level)
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
    ACT = "act"     # C-series: C2022A00007  (API collection: "Act")
    LI  = "li"      # F-series: F2022L00001  (API collection: "LegislativeInstrument")
    NI  = "ni"      # F-series: F2022N00001  (API collection: "NotifiableInstrument")

# API collection → AULegislationType mapping
AU_COLLECTION_MAP = {
    "Act": AULegislationType.ACT,
    "LegislativeInstrument": AULegislationType.LI,
    "NotifiableInstrument": AULegislationType.NI,
}
```

### Scraper — ✅ REST API confirmed

`legislation.gov.au` has a proper REST API at `https://api.prod.legislation.gov.au`.
No HTML scraping needed. See `docs/legislation-gov-au-api.md` for full details.

**Three-step fetch per title:**
```python
# 1. List all titles of a given collection type (paginated, 100/page)
GET /v1/titles?$top=100&$skip={offset}&$filter=collection eq 'Act'
→ fields: id (title_id), name, collection, status, year, number, makingDate, isPrincipal

# 2. Get latest compilation for a title
GET /v1/versions?$filter=titleId eq '{title_id}' and isLatest eq true&$top=1
→ fields: registerId (compilation ID), compilationNumber, start (compilation date), status

# 3a. Get EPUB document metadata (for section-level parsing)
GET /v1/Documents?$filter=titleId eq '{title_id}' and type eq 'Primary' and format eq 'Epub'&$orderby=start desc&$top=1
→ fields: start, retrospectiveStart, rectificationVersionNumber, uniqueTypeNumber, volumeNumber

# 3b. Download the EPUB (or DOCX) as binary ZIP bytes
GET /v1/documents(titleid='{id}',start={date},retrospectivestart={date},
    rectificationversionnumber=0,type='Primary',uniqueTypeNumber=0,volumeNumber=0,format='Epub')
→ returns binary EPUB/ZIP bytes
```

**Rate limiting**: 1 req/sec (no HTTP 436 — only 429). Remove 436 from `http.py`.

**Register ID format** (confirmed):
- `C2022A00007` — original Act (year 2022, number 7)
- `C2024C00838` — Compilation 38 of an existing Act
- `F2022L00001` — Legislative Instrument
- `F2022N00001` — Notifiable Instrument

**Public web URL** (for `uri` field): `https://www.legislation.gov.au/Details/{register_id}`

**Scale**: ~5,000 Acts in force; ~50,000 total titles across all collections.

### Parser — EPUB HTML (not CLML XML)

**This is the key difference from the UK approach.** AU legislation is downloaded as EPUB
(for sections) or DOCX (for full text). There is no CLML XML exposed via the API.

The UK `xml_parser.py` is **not reused** for AU. Instead:

**`epub_parser.py`** — section-level content from EPUB:
```
EPUB is a ZIP archive containing HTML files in OEBPS/:
  document.epub/
  └── OEBPS/
      ├── toc.ncx          → table of contents (section titles + order)
      ├── document_1.html  → sections 1–N (or Part 1)
      ├── document_2.html  → sections N+1–M (or Part 2)
      └── ...

Each HTML file contains:
  <h2 class="sectionNo">4  Definitions</h2>
  <p class="bodyText">In this Act:</p>
  ...
```

Parser logic:
1. `zipfile.ZipFile(epub_bytes)` → open the EPUB ZIP
2. Read `toc.ncx` or `content.opf` to get ordered list of HTML files
3. For each HTML file: BeautifulSoup parse → extract `<h2>` section headings + `<p>` body text
4. Yield one `AULegislationSection` per heading block

**`docx_parser.py`** — full text from DOCX (for legislation-level embeddings):
```python
import zipfile, re
from io import BytesIO
from bs4 import BeautifulSoup

def extract_text_from_docx(docx_bytes: bytes) -> str:
    with zipfile.ZipFile(BytesIO(docx_bytes)) as z:
        xml = z.read("word/document.xml")
    soup = BeautifulSoup(xml, "xml")
    paragraphs = [p.get_text(" ") for p in soup.find_all("w:p")]
    return " ".join(p.strip() for p in paragraphs if p.strip())
```

**Two-download strategy per title** (mirrors UK two-collection approach):
```python
# For AULegislation record: download DOCX → extract full text
# For AULegislationSection records: download EPUB → parse HTML per section
# Both downloads use the same /v1/documents endpoint, different format= param
```

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
    # EPUB/DOCX parsing (stdlib zipfile handles ZIP; bs4 for HTML; lxml for DOCX XML)
    # bs4 + lxml already in main deps — no new deps needed for parser
]
```

Note: `zipfile` is Python stdlib. `beautifulsoup4` and `lxml` are already in the main
`pyproject.toml` dependencies. No additional parser dependencies are needed.

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
1. ~~Research `legislation.gov.au` API~~ ✅ Done — see `docs/legislation-gov-au-api.md`
2. `src/lex_au/models.py` — AU types, AULegislation, AULegislationSection
3. `src/lex_au/settings.py` — AU config + Vectorize settings
4. `src/lex_au/core/embeddings.py` — sentence-transformers + CUDA + BM25 hashing
5. `src/lex_au/core/vectorize_client.py` — REST upsert client
6. `src/lex_au/legislation/scraper.py` — REST API client for `api.prod.legislation.gov.au`
7. `src/lex_au/legislation/parser/docx_parser.py` — DOCX full-text extraction
8. `src/lex_au/legislation/parser/epub_parser.py` — EPUB HTML → section list
9. `src/lex_au/legislation/pipeline.py` + `src/lex_au/ingest/` — orchestration + CLI
10. Test run: `--type act --year 2022 --limit 10`

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

| Risk | Status | Mitigation |
|---|---|---|
| `legislation.gov.au` API undocumented | ✅ Resolved | REST API at `api.prod.legislation.gov.au` confirmed, no auth needed |
| AU CLML namespace differences | ✅ N/A | Not using CLML XML — using EPUB HTML instead |
| EPUB internal HTML structure varies by Act | 🟡 Low | Use `toc.ncx` for ordered file list; fallback to alphabetical HTML file order |
| Large Acts split across multiple EPUB volumes | 🟡 Medium | Check `volumeNumber` in document metadata; download each volume separately |
| Vectorize sparse vector Worker binding unavailable | 🟡 Medium | Fall back to dense-only search for MVP |
| BM25 hash mismatch between Python and TypeScript | 🟡 Low-medium | Write cross-language test with 10 sample texts before deploying Plan B |
| Vectorize `getByIds()` unavailable | 🟡 Low | Use `$in` metadata filter query as fallback |
| EPUB unavailable for some old legislation | 🟡 Low | Fall back to `format='Word'` (DOCX) and extract text without section structure |

---

## Reference Files

These existing files are the direct templates for the AU equivalents:

| AU file | Template from | Notes |
|---|---|---|
| `src/lex_au/core/embeddings.py` | `src/lex/core/embeddings.py` | Replace Azure OAI with sentence-transformers |
| `src/lex_au/core/http.py` | `src/lex/core/http.py` | Remove HTTP 436 (UK-specific); base URL → `api.prod.legislation.gov.au` |
| `src/lex_au/legislation/scraper.py` | **New** — REST API, not a scraper | Uses `httpx` against `/v1/titles`, `/v1/versions`, `/v1/documents` |
| `src/lex_au/legislation/parser/docx_parser.py` | **New** — no UK equivalent | `zipfile` + `lxml` to extract text from DOCX XML |
| `src/lex_au/legislation/parser/epub_parser.py` | **New** — no UK equivalent | `zipfile` + `BeautifulSoup` to parse EPUB HTML into sections |
| `src/lex_au/ingest/orchestrator.py` | `src/lex/ingest/orchestrator.py` | Replace Qdrant with Vectorize client; adapt for two-download pattern |
| `workers/lex-au/src/routes/legislation.ts` | `src/backend/legislation/search.py` | Port two-tier search to TypeScript |
| `workers/lex-au/src/vectorize/fusion.ts` | DBSF logic in `src/backend/legislation/search.py` | Min-max normalisation approximation |
