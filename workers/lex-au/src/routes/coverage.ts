import { Hono } from "hono";
import type { Env } from "../env";
import { embedQuery, queryIndex } from "../vectorize/client";

type CoverageType = "act" | "li" | "ni";

interface CoverageFilters {
  yearFrom: number;
  yearTo: number;
  types: CoverageType[];
}

interface CoverageResult {
  filters: CoverageFilters;
  expectedIds: string[];
  indexedIds: string[];
  missingIds: string[];
  warnings: string[];
}

const SOURCE_API_BASE = "https://api.prod.legislation.gov.au/v1";
const TYPE_TO_COLLECTION: Record<CoverageType, string> = {
  act: "Act",
  li: "LegislativeInstrument",
  ni: "NotifiableInstrument",
};

const coverage = new Hono<{ Bindings: Env }>();

coverage.get("/coverage", async (c) => {
  const filters = parseFilters(c.req.url);
  const result = await buildCoverage(c.env, filters);

  const expectedCount = result.expectedIds.length;
  const indexedCount = result.indexedIds.length;
  const missingCount = result.missingIds.length;
  const coveragePct = expectedCount === 0 ? 100 : (indexedCount / expectedCount) * 100;

  const query = new URLSearchParams();
  query.set("year_from", String(filters.yearFrom));
  query.set("year_to", String(filters.yearTo));
  for (const type of filters.types) query.append("type", type);

  return c.html(`<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>lex-au coverage</title>
<style>
  :root {
    --bg: #ffffff;
    --fg: #0b1220;
    --muted: #4b5563;
    --card: #f8fafc;
    --border: #d1d5db;
    --accent: #0b4f8b;
    --ok: #047857;
    --warn: #b45309;
    --max: 960px;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0b1220;
      --fg: #e5e7eb;
      --muted: #9ca3af;
      --card: #111827;
      --border: #1f2937;
      --accent: #4f8fd0;
      --ok: #34d399;
      --warn: #f59e0b;
    }
  }
  body {
    margin: 0;
    font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--fg);
    padding: 16px;
  }
  main { max-width: var(--max); margin: 0 auto; }
  h1 { margin: 0 0 8px; }
  p { margin: 0 0 12px; color: var(--muted); }
  form {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 10px;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--card);
    margin-bottom: 14px;
  }
  label { font-size: 0.9rem; color: var(--muted); display: block; margin-bottom: 6px; }
  input, select, button {
    width: 100%;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px 10px;
    background: var(--bg);
    color: var(--fg);
    min-height: 40px;
  }
  button {
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
    font-weight: 600;
    cursor: pointer;
    align-self: end;
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 10px;
    margin: 12px 0 16px;
  }
  .card {
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px;
    background: var(--card);
  }
  .card h2 { margin: 0; font-size: 0.95rem; color: var(--muted); }
  .metric { margin-top: 6px; font-size: 1.5rem; font-weight: 700; }
  .metric.ok { color: var(--ok); }
  .metric.warn { color: var(--warn); }
  ul {
    margin: 0;
    padding-left: 1.25rem;
    max-height: 320px;
    overflow: auto;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--card);
    padding-top: 10px;
    padding-bottom: 10px;
  }
  li { margin: 4px 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .links { margin-top: 12px; }
  a { color: var(--accent); }
</style>
</head>
<body>
<main>
  <h1>Coverage dashboard</h1>
  <p>Compare source-of-truth titles from legislation.gov.au against vectors indexed in Cloudflare Vectorize.</p>

  <form method="get" action="/coverage">
    <div>
      <label for="year_from">Year from</label>
      <input id="year_from" name="year_from" type="number" min="1901" max="2100" value="${filters.yearFrom}" />
    </div>
    <div>
      <label for="year_to">Year to</label>
      <input id="year_to" name="year_to" type="number" min="1901" max="2100" value="${filters.yearTo}" />
    </div>
    <div>
      <label for="type">Type</label>
      <select id="type" name="type">
        <option value="act" ${filters.types.length === 1 && filters.types[0] === "act" ? "selected" : ""}>Act</option>
        <option value="li" ${filters.types.length === 1 && filters.types[0] === "li" ? "selected" : ""}>Legislative instrument</option>
        <option value="ni" ${filters.types.length === 1 && filters.types[0] === "ni" ? "selected" : ""}>Notifiable instrument</option>
        <option value="all" ${filters.types.length === 3 ? "selected" : ""}>All types</option>
      </select>
    </div>
    <div>
      <button type="submit">Run check</button>
    </div>
  </form>

  <section class="cards" aria-label="coverage summary">
    <article class="card">
      <h2>Expected titles</h2>
      <div class="metric">${expectedCount}</div>
    </article>
    <article class="card">
      <h2>Indexed titles</h2>
      <div class="metric">${indexedCount}</div>
    </article>
    <article class="card">
      <h2>Missing titles</h2>
      <div class="metric ${missingCount > 0 ? "warn" : "ok"}">${missingCount}</div>
    </article>
    <article class="card">
      <h2>Coverage</h2>
      <div class="metric ${coveragePct < 100 ? "warn" : "ok"}">${coveragePct.toFixed(2)}%</div>
    </article>
  </section>

  ${result.warnings.length > 0 ? `<div style="border:1px solid var(--warn); border-radius:10px; padding:10px; margin:12px 0;">${result.warnings.map((w) => `<p style="margin:0 0 4px; color:var(--warn)">${escapeHtml(w)}</p>`).join("")}</div>` : ""}

  <h2>Missing IDs (first 200)</h2>
  <ul>
    ${result.missingIds.slice(0, 200).map((id) => `<li>${escapeHtml(id)}</li>`).join("") || "<li>None</li>"}
  </ul>

  <p class="links">
    JSON: <a href="/coverage.json?${query.toString()}">/coverage.json</a>
  </p>
</main>
</body>
</html>`);
});

coverage.get("/coverage.json", async (c) => {
  const filters = parseFilters(c.req.url);
  const page = parsePositiveInt(c.req.query("page"), 1);
  const pageSize = Math.min(parsePositiveInt(c.req.query("page_size"), 100), 500);

  const result = await buildCoverage(c.env, filters);

  const expectedCount = result.expectedIds.length;
  const indexedCount = result.indexedIds.length;
  const missingCount = result.missingIds.length;
  const coveragePct = expectedCount === 0 ? 100 : (indexedCount / expectedCount) * 100;

  const start = (page - 1) * pageSize;
  const pagedMissingIds = result.missingIds.slice(start, start + pageSize);

  return c.json({
    filters,
    totals: {
      expected: expectedCount,
      indexed: indexedCount,
      missing: missingCount,
      coverage_pct: Number(coveragePct.toFixed(4)),
    },
    pagination: {
      page,
      page_size: pageSize,
      total_missing: missingCount,
      total_pages: Math.max(1, Math.ceil(missingCount / pageSize)),
    },
    missing_ids: pagedMissingIds,
    warnings: result.warnings,
  });
});

async function buildCoverage(env: Env, filters: CoverageFilters): Promise<CoverageResult> {
  const { ids: expectedIds, warnings } = await fetchSourceIds(filters);
  const indexedIds = await fetchIndexedIds(env, expectedIds);
  const indexedSet = new Set(indexedIds);
  const missingIds = expectedIds.filter((id) => !indexedSet.has(id));

  return {
    filters,
    expectedIds,
    indexedIds,
    missingIds,
    warnings,
  };
}

async function fetchSourceIds(
  filters: CoverageFilters,
): Promise<{ ids: string[]; warnings: string[] }> {
  const discovered = new Set<string>();
  const warnings: string[] = [];

  for (let year = filters.yearFrom; year <= filters.yearTo; year += 1) {
    for (const type of filters.types) {
      const collection = TYPE_TO_COLLECTION[type];
      let skip = 0;
      const top = 200;
      let usePrincipalFilter = true;

      while (true) {
        const filterText = usePrincipalFilter
          ? `year eq ${year} and collection eq '${collection}' and isPrincipal eq true`
          : `year eq ${year} and collection eq '${collection}'`;

        const params = new URLSearchParams({
          "$select": "id",
          "$filter": filterText,
          "$orderby": "id",
          "$top": String(top),
          "$skip": String(skip),
        });

        const response = await fetch(`${SOURCE_API_BASE}/titles?${params.toString()}`);
        if (!response.ok) {
          if (response.status === 400 && usePrincipalFilter) {
            usePrincipalFilter = false;
            skip = 0;
            warnings.push(`Source API rejected isPrincipal filter for ${type}:${year}; retried without it.`);
            continue;
          }

          if (response.status === 400) {
            warnings.push(`Skipping invalid source query for ${type}:${year} (HTTP 400).`);
            break;
          }

          warnings.push(`Source API failed for ${type}:${year} (HTTP ${response.status}).`);
          break;
        }

        const body = await response.json<{ value?: Array<{ id?: string }> }>();
        const items = body.value ?? [];
        for (const item of items) {
          if (item.id) discovered.add(item.id);
        }

        if (items.length < top) break;
        skip += items.length;
      }
    }
  }

  return { ids: Array.from(discovered).sort(), warnings };
}

async function fetchIndexedIds(env: Env, expectedIds: string[]): Promise<string[]> {
  if (expectedIds.length === 0) return [];

  const probeVector = await embedQuery(env.AI, "coverage probe");
  const indexedIds = new Set<string>();

  const concurrency = 8;
  let cursor = 0;

  async function worker(): Promise<void> {
    while (true) {
      const index = cursor;
      cursor += 1;
      if (index >= expectedIds.length) return;

      const id = expectedIds[index]!;
      const matches = await queryIndex(env.LEGISLATION_INDEX, probeVector, {
        topK: 1,
        filter: { id },
      });

      if ((matches.matches?.length ?? 0) > 0) {
        indexedIds.add(id);
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(concurrency, expectedIds.length) }, () => worker()));
  return Array.from(indexedIds).sort();
}

function parseFilters(rawUrl: string): CoverageFilters {
  const url = new URL(rawUrl);
  const now = new Date().getUTCFullYear();

  let yearFrom = parsePositiveInt(url.searchParams.get("year_from"), 1901);
  let yearTo = parsePositiveInt(url.searchParams.get("year_to"), now);
  if (yearFrom > yearTo) {
    [yearFrom, yearTo] = [yearTo, yearFrom];
  }

  const requestedType = (url.searchParams.get("type") ?? "act").toLowerCase();
  const types: CoverageType[] = requestedType === "all"
    ? ["act", "li", "ni"]
    : isCoverageType(requestedType)
      ? [requestedType]
      : ["act"];

  return { yearFrom, yearTo, types };
}

function parsePositiveInt(value: string | null | undefined, defaultValue: number): number {
  if (!value) return defaultValue;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : defaultValue;
}

function isCoverageType(value: string): value is CoverageType {
  return value === "act" || value === "li" || value === "ni";
}

function escapeHtml(input: string): string {
  return input
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export { coverage };
