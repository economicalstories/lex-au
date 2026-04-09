# legislation.gov.au API — Research Notes

Equivalent of `docs/legislation-gov-uk-api.md` for the Australian Federal Register of Legislation.
Documents the API behaviour discovered through research, for use in building `src/lex_au/scraper.py`.

---

## TL;DR

There is a **proper, documented REST API** at `https://api.prod.legislation.gov.au`.
No authentication required. No Atom feed scraping needed. This is cleaner than the UK approach.

```
GET https://api.prod.legislation.gov.au/v1/titles?$top=100&$skip=0&$filter=collection eq 'Act'
→ paginated list of all Commonwealth Acts with metadata

GET https://api.prod.legislation.gov.au/v1/versions?$filter=titleId eq 'C1901A00002' and isLatest eq true
→ current compilation info (registerId, compilationNumber, start date)

GET https://api.prod.legislation.gov.au/v1/documents(...)
→ download EPUB or DOCX file containing full text
```

---

## API Base

```
https://api.prod.legislation.gov.au
```

No authentication required. Open data, Creative Commons licence.

**Rate limit**: 1 request/second (burst: 3). Recommended to avoid peak hours 0800–2000 AEST
for large bulk operations. Contact `feedback@legislation.gov.au` before very large scrapes.

---

## Endpoints

### 1. List all titles (paginated)

```
GET /v1/titles?$top={n}&$skip={offset}
GET /v1/titles?$top=100&$skip=0&$filter=collection eq 'Act'
```

OData-style pagination. Max page size: 1000 (use 100 as safe default).

**Response**:
```json
{
  "value": [
    {
      "id": "C1901A00002",
      "name": "Acts Interpretation Act 1901",
      "collection": "Act",
      "status": "InForce",
      "makingDate": "1901-07-12",
      "year": 1901,
      "number": 2,
      "isPrincipal": true,
      "seriesType": "Act"
    },
    ...
  ]
}
```

### 2. Count titles

```
GET /v1/titles/$count
GET /v1/titles/$count?$filter=collection eq 'Act'
```

Returns a plain integer. Useful for computing total pages before paginating.

### 3. Get a specific title

```
GET /v1/titles/{title_id}
```

Returns the same fields as above for a single title.

### 4. Get latest compilation (version) for a title

```
GET /v1/versions?$filter=titleId eq '{title_id}' and isLatest eq true&$top=1
```

**Response**:
```json
{
  "value": [
    {
      "registerId": "C2024C00838",
      "titleId": "C1901A00002",
      "isLatest": true,
      "start": "2024-12-11",
      "status": "InForce",
      "compilationNumber": "38",
      "name": "Acts Interpretation Act 1901"
    }
  ]
}
```

`registerId` is the compilation-specific ID used for downloading the document.

### 5. Get document metadata (find download parameters)

```
GET /v1/Documents?$filter=titleId eq '{title_id}' and type eq 'Primary' and format eq 'Epub'&$orderby=start desc&$top=1
```

Prefer EPUB format (structured). Fall back to Word (`format eq 'Word'`) if EPUB unavailable.

**Response fields**:
```json
{
  "value": [
    {
      "titleId": "C1901A00002",
      "start": "2024-12-11",
      "retrospectiveStart": "1901-07-12",
      "rectificationVersionNumber": 0,
      "type": "Primary",
      "uniqueTypeNumber": 0,
      "volumeNumber": 0,
      "format": "Epub"
    }
  ]
}
```

### 6. Download document

```
GET /v1/documents(titleid='{titleId}',start={start},retrospectivestart={retrospectiveStart},rectificationversionnumber={n},type='{type}',uniqueTypeNumber={n},volumeNumber={n},format='{format}')
```

All parameters come from the document metadata response above.

Returns binary bytes (ZIP file — either EPUB or DOCX archive).

**Example URL**:
```
GET /v1/documents(titleid='C1901A00002',start=2024-12-11,retrospectivestart=1901-07-12,rectificationversionnumber=0,type='Primary',uniqueTypeNumber=0,volumeNumber=0,format='Epub')
```

---

## Collections (Legislation Types)

| Collection value | Description | AU type code |
|---|---|---|
| `Act` | Commonwealth Acts | `act` |
| `LegislativeInstrument` | Legislative Instruments | `li` |
| `NotifiableInstrument` | Notifiable Instruments | `ni` |
| `Constitution` | Australian Constitution | (skip — single document) |
| `AdministrativeArrangementsOrder` | Admin Arrangements Orders | (optional) |
| `ContinuedLaw` | Pre-federation continued laws | (optional) |
| `PrerogativeInstrument` | Prerogative instruments | (skip) |

**In scope for v1**: `Act`, `LegislativeInstrument`, `NotifiableInstrument`

---

## Register ID Format

```
C1901A00001   → Commonwealth, year 1901, original Act (A), number 00001
C2022A00007   → Commonwealth, year 2022, original Act (A), number 00007
C2024C00838   → Commonwealth, year 2024, Compilation (C), number 00838
F2022L00001   → F-series, year 2022, Legislative instrument (L), number 00001
F2022N00001   → F-series, year 2022, Notifiable instrument (N), number 00001
```

**Series ID** (`title_id`): the original Act ID, constant across all compilations.
e.g. `C1901A00002` = Acts Interpretation Act 1901, unchanged since 1901.

**Compilation ID** (`registerId`): changes with each amendment compilation.
e.g. `C2024C00838` = Acts Interpretation Act 1901, Compilation 38, as of Dec 2024.

The scraper should:
1. Enumerate all `title_id` values via `/v1/titles`
2. For each title, get the latest `registerId` via `/v1/versions`
3. Download using the `registerId`'s document metadata

---

## Web URL Pattern

```
https://www.legislation.gov.au/Details/{register_id}
```

Example: `https://www.legislation.gov.au/Details/C2024C00838`

This is the canonical public URL for a compilation. Use as the `uri` field in data models.

---

## Sample Normalized Record

From `worldwidelaw/legal-sources` — what a fully processed Act record looks like:

```json
{
  "_id": "C2024C00838",
  "title": "Acts Interpretation Act 1901",
  "text": "...(full concatenated text)...",
  "date": "2024-12-11",
  "url": "https://www.legislation.gov.au/Details/C2024C00838",
  "register_id": "C2024C00838",
  "title_id": "C1901A00002",
  "collection": "Act",
  "status": "InForce",
  "making_date": "1901-07-12",
  "compilation_number": "38",
  "year": 1901,
  "number": 2,
  "is_principal": true,
  "series_type": "Act",
  "language": "en"
}
```

And the oldest Act (no compilation — original only):
```json
{
  "_id": "C1901A00001",
  "title": "Consolidated Revenue",
  "register_id": "C1901A00001",
  "title_id": "C1901A00001",
  "collection": "Act",
  "status": "Repealed",
  "compilation_number": "0",
  "year": 1901,
  "number": 1,
  "is_principal": true
}
```

---

## Text Extraction Strategy

The API does not return structured section-level XML like the UK CLML approach.
Documents are downloaded as EPUB or DOCX (both are ZIP archives).

### Option A: EPUB (recommended for section splitting)

EPUB is a ZIP containing HTML files. Typically one HTML file per section or group of sections.
Structure example:
```
document.epub (ZIP)
├── OEBPS/
│   ├── document_1.html   → Part 1, sections 1–10
│   ├── document_2.html   → Part 2, sections 11–30
│   └── ...
```

HTML files contain structured headings (`<h2>`, `<h3>`) for sections and subsections.
Parse with BeautifulSoup: extract section headings + paragraph text per section.

**Important**: EPUB URLs for individual versions are also directly accessible:
```
https://www.legislation.gov.au/{register_id}/asmade/{date}/text/original/epub/OEBPS/document_1/document_1.html
```
(seen in search results — but prefer the API download endpoint above)

### Option B: DOCX (simpler, full text only)

DOCX is a ZIP containing `word/document.xml` (Office Open XML).
The XML contains paragraph elements with section heading styles.
Parse with `python-docx` or raw XML to extract text.

This is what `worldwidelaw/legal-sources` does — extracts full concatenated text, no sections.
**Not suitable for section-level embedding**, but usable for legislation-level embeddings.

### Recommended approach for `src/lex_au/`

```
For AULegislation (act-level records):  download DOCX, extract full text
For AULegislationSection records:       download EPUB, parse HTML per section
```

This mirrors the UK pipeline's two-tier approach (legislation + legislation_section collections).

---

## Incremental Updates

For daily/weekly refresh, use the `registeredAt` filter on `/v1/versions`:

```
GET /v1/versions?$filter=registeredAt ge 2024-12-01T00:00:00Z&$orderby=registeredAt desc
```

This returns all compilations registered since a given date. Cross-reference with existing
`compilation_number` values to find new or updated compilations.

---

## Scale

- **Acts**: ~5,000 currently in force + ~3,000 repealed = ~8,000 titles
- **Legislative Instruments**: ~15,000 current + historical
- **Notifiable Instruments**: ~8,000
- **Total across all collections**: ~50,000+ titles

Per the README: "approximately 50,000+ legislative titles" from 1901 to present.

For initial ingestion, focus on `Act` (InForce) = ~5,000 titles.
Full AU corpus is well within Cloudflare Vectorize's 5M vector limit
even at section-level granularity (typical Act has 50–200 sections).

---

## Key Differences vs legislation.gov.uk

| Aspect | UK | AU |
|---|---|---|
| Discovery | Atom feeds + HTML scraping | REST API `/v1/titles` |
| Document format | CLML XML (structured, sections as elements) | EPUB (HTML) or DOCX |
| Section structure | Native `<P1>` CLML elements | Must parse from EPUB HTML headings |
| Rate limiting | HTTP 429 + proprietary 436 | 1 req/sec (just 429) |
| Authentication | None | None |
| Historical | From 1267 (regnal years) | From 1901 (Federation) |
| Amendment tracking | Rich amendment XML metadata | Not natively exposed in API |
| Explanatory notes | Available via XML | Not available via this API |

---

## HTTP Client Notes

Reuse `src/lex/core/http.py` `HttpClient` with these changes:
- Base URL: `https://api.prod.legislation.gov.au`
- Remove HTTP 436 from rate-limit detection (UK-specific) — only handle 429
- Set `cache_ttl=86400` (24h) — legislation changes slowly
- Default rate: 1 req/sec — configure via `requests-ratelimiter` or `AdaptiveRateLimiter`

---

## References

- Federal Register of Legislation: https://www.legislation.gov.au
- API base (discovered): https://api.prod.legislation.gov.au
- Example scraper: https://github.com/worldwidelaw/legal-sources/tree/main/sources/AU/FederalRegister
- Office of Parliamentary Counsel (maintains the register): https://www.opc.gov.au/FRL
- Bulk operations contact: feedback@legislation.gov.au
