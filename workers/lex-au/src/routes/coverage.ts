import { Hono } from "hono";
import type { Env } from "../env";

type CoverageType = "act" | "li" | "ni";

interface CoverageFilters {
  yearFrom: number;
  yearTo: number;
  types: CoverageType[];
  maxIdsToCheck: number;
}

interface CoverageResult {
  filters: CoverageFilters;
  expectedIds: string[];
  indexedIds: string[];
  missingIds: string[];
  warnings: string[];
}

const SOURCE_WEB_BASE = "https://www.legislation.gov.au";
const MAX_IDS_TO_CHECK_HARD_CAP = 4000;
const VECTORIZE_GET_BY_IDS_BATCH = 100;
const MAX_YEAR_SPAN = 5;

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
  query.set("max_ids", String(filters.maxIdsToCheck));
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
  body { margin: 0; font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--fg); padding: 16px; }
  main { max-width: var(--max); margin: 0 auto; }
  h1 { margin: 0 0 8px; }
  p { margin: 0 0 12px; color: var(--muted); }
  form { display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 10px; padding: 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--card); margin-bottom: 14px; align-items: end; }
  label { font-size: 0.9rem; color: var(--muted); display: block; margin-bottom: 6px; }
  input, select, button { width: 100%; border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; background: var(--bg); color: var(--fg); min-height: 40px; }
  button { background: var(--accent); color: #fff; border-color: var(--accent); font-weight: 600; cursor: pointer; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin: 12px 0 16px; }
  .card { border: 1px solid var(--border); border-radius: 10px; padding: 12px; background: var(--card); }
  .card h2 { margin: 0; font-size: 0.95rem; color: var(--muted); }
  .metric { margin-top: 6px; font-size: 1.5rem; font-weight: 700; }
  .metric.ok { color: var(--ok); }
  .metric.warn { color: var(--warn); }
  ul { margin: 0; padding-left: 1.25rem; max-height: 320px; overflow: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--card); padding-top: 10px; padding-bottom: 10px; }
  li { margin: 4px 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .links { margin-top: 12px; }
  a { color: var(--accent); }
  .actions { display: flex; gap: 10px; align-items: end; }
  .actions button { max-width: 220px; }
  @media (max-width: 860px) { form { grid-template-columns: repeat(2, minmax(160px, 1fr)); } }
  @media (max-width: 520px) { form { grid-template-columns: 1fr; } .actions button { max-width: none; } }
</style>
</head>
<body>
<main>
  <h1>Coverage dashboard</h1>
  <p>Compares source-of-truth titles from legislation.gov.au against vectors indexed in Cloudflare Vectorize.</p>

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
      <label for="max_ids">Max IDs to check</label>
      <input id="max_ids" name="max_ids" type="number" min="100" max="${MAX_IDS_TO_CHECK_HARD_CAP}" step="100" value="${filters.maxIdsToCheck}" />
    </div>
    <div class="actions">
      <button type="submit">Run check</button>
    </div>
  </form>

  <section class="cards" aria-label="coverage summary">
    <article class="card"><h2>Expected titles (checked)</h2><div class="metric">${expectedCount}</div></article>
    <article class="card"><h2>Indexed titles</h2><div class="metric">${indexedCount}</div></article>
    <article class="card"><h2>Missing titles</h2><div class="metric ${missingCount > 0 ? "warn" : "ok"}">${missingCount}</div></article>
    <article class="card"><h2>Coverage</h2><div class="metric ${coveragePct < 100 ? "warn" : "ok"}">${coveragePct.toFixed(2)}%</div></article>
  </section>

  ${result.warnings.length > 0 ? `<div style="border:1px solid var(--warn); border-radius:10px; padding:10px; margin:12px 0;">${result.warnings.map((w) => `<p style="margin:0 0 4px; color:var(--warn)">${escapeHtml(w)}</p>`).join("")}</div>` : ""}

  <h2>Missing IDs (first 200)</h2>
  <ul>
    ${result.missingIds.slice(0, 200).map((id) => `<li>${escapeHtml(id)}</li>`).join("") || "<li>None</li>"}
  </ul>

  <p class="links">JSON: <a href="/coverage.json?${query.toString()}">/coverage.json</a></p>
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
    filters: result.filters,
    totals: {
      expected_checked: expectedCount,
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
  const warnings: string[] = [];
  let effectiveFilters = filters;
  const span = filters.yearTo - filters.yearFrom + 1;
  if (span > MAX_YEAR_SPAN) {
    effectiveFilters = { ...filters, yearTo: filters.yearFrom + MAX_YEAR_SPAN - 1 };
    warnings.push(`Year range limited to ${MAX_YEAR_SPAN} years per request (${effectiveFilters.yearFrom}-${effectiveFilters.yearTo}) to keep coverage checks fast and reliable.`);
  }

  const sourceResult = await fetchSourceIds(effectiveFilters);
  warnings.push(...sourceResult.warnings);
  const sourceIds = sourceResult.ids;

  let expectedIds = sourceIds;
  if (sourceIds.length > filters.maxIdsToCheck) {
    expectedIds = sourceIds.slice(0, filters.maxIdsToCheck);
    warnings.push(
      `Checked first ${filters.maxIdsToCheck} IDs out of ${sourceIds.length} source IDs to stay within Worker subrequest limits. Narrow filters for full-fidelity checks.`,
    );
  }

  const indexedIds = await fetchIndexedIds(env, expectedIds);
  const indexedSet = new Set(indexedIds);
  const missingIds = expectedIds.filter((id) => !indexedSet.has(id));

  return {
    filters: effectiveFilters,
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
    const feedIdsByType = await fetchYearIdsFromFeed(year, warnings);
    for (const type of filters.types) {
      for (const id of feedIdsByType[type]) {
        discovered.add(id);
      }
    }
  }

  return { ids: Array.from(discovered).sort(), warnings };
}

async function fetchYearIdsFromFeed(
  year: number,
  warnings: string[],
): Promise<Record<CoverageType, Set<string>>> {
  const byType: Record<CoverageType, Set<string>> = {
    act: new Set<string>(),
    li: new Set<string>(),
    ni: new Set<string>(),
  };

  for (let page = 1; page <= 200; page += 1) {
    const url = `${SOURCE_WEB_BASE}/primary+secondary/${year}/data.feed?page=${page}`;
    const response = await fetch(url);
    if (!response.ok) {
      if (page === 1) {
        warnings.push(`Source feed failed for ${year} (HTTP ${response.status}).`);
      }
      break;
    }

    const xml = await response.text();
    const ids = extractTitleIdsFromFeed(xml);
    if (ids.length === 0) break;

    for (const id of ids) {
      const type = typeFromTitleId(id);
      if (type) byType[type].add(id);
    }

    if (!xml.includes('rel="next"')) break;
  }

  return byType;
}

function extractTitleIdsFromFeed(xml: string): string[] {
  const ids = new Set<string>();
  const titleIdPattern = /(?:id|href)="[^"]*\/([CF]\d{4}[ALN]\d{5})(?:["/\?#]|$)/g;

  let match = titleIdPattern.exec(xml);
  while (match) {
    ids.add(match[1]!);
    match = titleIdPattern.exec(xml);
  }

  return Array.from(ids);
}

function typeFromTitleId(titleId: string): CoverageType | null {
  const marker = titleId[5];
  if (marker === "A") return "act";
  if (marker === "L") return "li";
  if (marker === "N") return "ni";
  return null;
}

async function fetchIndexedIds(env: Env, expectedIds: string[]): Promise<string[]> {
  if (expectedIds.length === 0) return [];

  const indexedIds = new Set<string>();

  for (let i = 0; i < expectedIds.length; i += VECTORIZE_GET_BY_IDS_BATCH) {
    const chunk = expectedIds.slice(i, i + VECTORIZE_GET_BY_IDS_BATCH);
    const vectors = await env.LEGISLATION_INDEX.getByIds(chunk);
    for (const vector of vectors) {
      if (vector.id) indexedIds.add(vector.id);
    }
  }

  return Array.from(indexedIds).sort();
}

function parseFilters(rawUrl: string): CoverageFilters {
  const url = new URL(rawUrl);
  const now = new Date().getUTCFullYear();

  let yearFrom = parsePositiveInt(url.searchParams.get("year_from"), Math.max(1901, now - 1));
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

  const requestedMaxIds = parsePositiveInt(url.searchParams.get("max_ids"), 2000);
  const maxIdsToCheck = Math.min(Math.max(requestedMaxIds, 100), MAX_IDS_TO_CHECK_HARD_CAP);

  return { yearFrom, yearTo, types, maxIdsToCheck };
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
