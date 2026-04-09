/**
 * Vectorize query helpers — embed via Workers AI, query Vectorize indexes.
 */

import type { Env } from "../env";
import type { SectionMetadata, LegislationMetadata } from "../types";
import { buildSparseVector } from "./sparse";
import { fuseScores } from "./fusion";

const EMBEDDING_MODEL = "@cf/baai/bge-large-en-v1.5" as const;
const MAX_TOP_K_WITH_FULL_METADATA = 50;

/** Generate a dense embedding via Workers AI. */
export async function embedQuery(
  ai: Ai,
  text: string,
): Promise<number[]> {
  const result = await ai.run(EMBEDDING_MODEL, { text: [text] });
  // Workers AI returns { data: number[][] } for embedding models
  const output = result as { data?: number[][] };
  if (!output.data || !output.data[0]) {
    throw new Error("Workers AI returned empty embedding result");
  }
  return output.data[0];
}

export interface VectorizeSearchOptions {
  topK?: number;
  filter?: VectorizeVectorMetadataFilter;
}

/** Query a Vectorize index with dense vector + optional metadata filter. */
export async function queryIndex(
  index: VectorizeIndex,
  vector: number[],
  options: VectorizeSearchOptions = {},
): Promise<VectorizeMatches> {
  const { topK = 20, filter } = options;
  // Cloudflare Vectorize caps full-metadata queries at topK <= 50.
  return index.query(vector, {
    topK: Math.min(topK, MAX_TOP_K_WITH_FULL_METADATA),
    filter,
    returnMetadata: "all",
  });
}

/** Search sections: embed query → query section index → return scored results. */
export async function searchSections(
  env: Env,
  query: string,
  options: {
    legislationId?: string;
    type?: string[];
    yearFrom?: number;
    yearTo?: number;
    size?: number;
    offset?: number;
  } = {},
): Promise<{ results: Array<{ metadata: SectionMetadata; score: number }>; total: number }> {
  const { size = 20, offset = 0 } = options;
  const fetchLimit = size + offset;

  const vector = await embedQuery(env.AI, query);
  const filter = buildSectionFilter(options);

  const matches = await queryIndex(env.LEGISLATION_SECTION_INDEX, vector, {
    topK: Math.min(fetchLimit, 100),
    filter: Object.keys(filter).length > 0 ? filter : undefined,
  });

  if (!matches.matches || matches.matches.length === 0) {
    return { results: [], total: 0 };
  }

  const maxScore = Math.max(...matches.matches.map((m) => m.score));
  const normFactor = maxScore > 0 ? maxScore : 1;

  const all = matches.matches.map((m) => ({
    metadata: m.metadata as unknown as SectionMetadata,
    score: m.score / normFactor,
  }));

  return {
    results: all.slice(offset, offset + size),
    total: all.length,
  };
}

/** Search legislation (acts): search sections → group by legislation_id → rank. */
export async function searchActs(
  env: Env,
  query: string,
  options: {
    type?: string[];
    yearFrom?: number;
    yearTo?: number;
    limit?: number;
    offset?: number;
  } = {},
): Promise<{
  results: Array<{
    metadata: LegislationMetadata | Record<string, unknown>;
    sections: Array<{ number: string; provision_type: string; score: number }>;
    score: number;
  }>;
  total: number;
  offset: number;
  limit: number;
}> {
  const { limit = 10, offset = 0 } = options;

  // Run section search and title search in parallel
  const vector = await embedQuery(env.AI, query);

  const sectionFilter = buildSectionFilter(options);
  const actFilter = buildActFilter(options);

  const [sectionMatches, actMatches] = await Promise.all([
    queryIndex(env.LEGISLATION_SECTION_INDEX, vector, {
      topK: 100,
      filter: Object.keys(sectionFilter).length > 0 ? sectionFilter : undefined,
    }),
    queryIndex(env.LEGISLATION_INDEX, vector, {
      topK: 20,
      filter: Object.keys(actFilter).length > 0 ? actFilter : undefined,
    }),
  ]);

  // Normalise act title scores
  const titleScores = new Map<string, number>();
  if (actMatches.matches && actMatches.matches.length > 0) {
    const maxActScore = Math.max(...actMatches.matches.map((m) => m.score));
    const norm = maxActScore > 0 ? maxActScore : 1;
    for (const m of actMatches.matches) {
      const id = (m.metadata as Record<string, unknown>)?.id as string | undefined;
      if (id) titleScores.set(id, m.score / norm);
    }
  }

  // Group sections by legislation_id
  type SectionEntry = { metadata: SectionMetadata; score: number };
  const grouped = new Map<string, SectionEntry[]>();
  const actMetadataMap = new Map<string, Record<string, unknown>>();

  if (sectionMatches.matches) {
    const maxSecScore = Math.max(...sectionMatches.matches.map((m) => m.score));
    const norm = maxSecScore > 0 ? maxSecScore : 1;
    for (const m of sectionMatches.matches) {
      const meta = m.metadata as unknown as SectionMetadata;
      const legId = meta.legislation_id;
      if (!legId) continue;
      const entry: SectionEntry = { metadata: meta, score: m.score / norm };
      const arr = grouped.get(legId) ?? [];
      arr.push(entry);
      grouped.set(legId, arr);
    }
  }

  // Store act metadata from title search
  if (actMatches.matches) {
    for (const m of actMatches.matches) {
      const meta = m.metadata as Record<string, unknown>;
      const id = meta?.id as string | undefined;
      if (id) actMetadataMap.set(id, meta);
    }
  }

  // Merge title scores: boost existing groups or create new entries
  for (const [legId, titleScore] of titleScores) {
    const existing = grouped.get(legId);
    if (existing) {
      for (const entry of existing) {
        entry.score = Math.min(1.0, entry.score + 0.3 * titleScore);
      }
    } else {
      grouped.set(legId, []);
    }
  }

  // Sort each group by score, keep top 10
  for (const [legId, entries] of grouped) {
    entries.sort((a, b) => b.score - a.score);
    grouped.set(legId, entries.slice(0, 10));
  }

  // Rank legislation by best section score
  const ranked = Array.from(grouped.entries())
    .map(([legId, entries]) => ({
      legId,
      bestScore: entries.length > 0
        ? Math.max(...entries.map((e) => e.score))
        : titleScores.get(legId) ?? 0,
      entries,
    }))
    .sort((a, b) => b.bestScore - a.bestScore);

  const total = ranked.length;
  const page = ranked.slice(offset, offset + limit);

  // Look up legislation metadata for paged results
  const legIds = page.map((r) => r.legId);
  const legMetadata = await batchLookupLegislation(env, legIds, actMetadataMap);

  const results = page.map((r) => ({
    metadata: legMetadata.get(r.legId) ?? { id: r.legId, title: "", status: "stub" },
    sections: r.entries.map((e) => ({
      number: e.metadata.number ?? "",
      provision_type: e.metadata.provision_type ?? "",
      score: e.score,
    })),
    score: r.bestScore,
  }));

  return { results, total, offset, limit };
}

/** Lookup a single piece of legislation by type + year + number. */
export async function lookupLegislation(
  env: Env,
  type: string,
  year: number,
  number: number,
): Promise<LegislationMetadata | null> {
  // Use metadata filtering on the legislation index with a dummy vector query
  // We need any vector to query — generate from the search terms
  const queryText = `${type} ${year} ${number}`;
  const vector = await embedQuery(env.AI, queryText);

  const matches = await queryIndex(env.LEGISLATION_INDEX, vector, {
    topK: 5,
    filter: { type, year, number },
  });

  if (!matches.matches || matches.matches.length === 0) return null;

  // Find exact match
  for (const m of matches.matches) {
    const meta = m.metadata as unknown as LegislationMetadata;
    if (meta.type === type && meta.year === year && meta.number === number) {
      return meta;
    }
  }

  return null;
}

/** Get all sections for a legislation_id. */
export async function getSections(
  env: Env,
  legislationId: string,
  limit: number = 200,
): Promise<SectionMetadata[]> {
  // Generate a neutral embedding, then filter by legislation_id
  const vector = await embedQuery(env.AI, legislationId);
  const matches = await queryIndex(env.LEGISLATION_SECTION_INDEX, vector, {
    topK: Math.min(limit, 100),
    filter: { legislation_id: legislationId },
  });

  if (!matches.matches) return [];

  const sections = matches.matches.map(
    (m) => m.metadata as unknown as SectionMetadata,
  );

  sections.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  return sections;
}

/** Get full text by fetching all sections and concatenating. */
export async function getFullText(
  env: Env,
  legislationId: string,
  includeSchedules: boolean = false,
): Promise<{ legislation: LegislationMetadata | null; fullText: string } | null> {
  // Fetch legislation metadata and sections in parallel
  const vector = await embedQuery(env.AI, legislationId);

  const [legMatches, secMatches] = await Promise.all([
    queryIndex(env.LEGISLATION_INDEX, vector, {
      topK: 5,
      filter: { id: legislationId },
    }),
    queryIndex(env.LEGISLATION_SECTION_INDEX, vector, {
      topK: 100,
      filter: { legislation_id: legislationId },
    }),
  ]);

  if (!legMatches.matches || legMatches.matches.length === 0) return null;

  const legislation = legMatches.matches[0]!.metadata as unknown as LegislationMetadata;

  const sections = (secMatches.matches ?? [])
    .map((m) => m.metadata as unknown as SectionMetadata)
    .filter((s) => includeSchedules || s.provision_type === "section")
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));

  // Vectorize metadata doesn't store full text — return section titles as structure
  const fullText = sections
    .map((s) => `${s.number} ${s.title}`)
    .join("\n\n");

  return {
    legislation,
    fullText: fullText || "Full text not available via vector index. Use the proxy endpoint to fetch live content.",
  };
}

// ── Filter builders ──────────────────────────────────────────────

function buildSectionFilter(options: {
  legislationId?: string;
  type?: string[];
  yearFrom?: number;
  yearTo?: number;
}): VectorizeVectorMetadataFilter {
  const filter: Record<string, unknown> = {};

  if (options.legislationId) {
    filter["legislation_id"] = options.legislationId;
    return filter as VectorizeVectorMetadataFilter;
  }

  if (options.type && options.type.length === 1) {
    filter["type"] = options.type[0];
  }
  if (options.yearFrom !== undefined && options.yearTo !== undefined && options.yearFrom === options.yearTo) {
    filter["year"] = options.yearFrom;
  } else {
    if (options.yearFrom !== undefined) {
      filter["year"] = { $gte: options.yearFrom };
    }
    if (options.yearTo !== undefined) {
      // Vectorize filter merging: if yearFrom already set a range, combine
      if (filter["year"] && typeof filter["year"] === "object") {
        (filter["year"] as Record<string, number>)["$lte"] = options.yearTo;
      } else if (!filter["year"]) {
        filter["year"] = { $lte: options.yearTo };
      }
    }
  }

  return filter as VectorizeVectorMetadataFilter;
}

function buildActFilter(options: {
  type?: string[];
  yearFrom?: number;
  yearTo?: number;
}): VectorizeVectorMetadataFilter {
  return buildSectionFilter(options);
}

/** Batch-lookup legislation metadata from the act index. */
async function batchLookupLegislation(
  env: Env,
  ids: string[],
  cachedMetadata: Map<string, Record<string, unknown>>,
): Promise<Map<string, Record<string, unknown>>> {
  const result = new Map<string, Record<string, unknown>>();

  for (const id of ids) {
    const cached = cachedMetadata.get(id);
    if (cached) {
      result.set(id, cached);
      continue;
    }

    // Fall back to querying (expensive but rare)
    const vector = await embedQuery(env.AI, id);
    const matches = await queryIndex(env.LEGISLATION_INDEX, vector, {
      topK: 3,
      filter: { id },
    });
    if (matches.matches && matches.matches.length > 0) {
      result.set(id, matches.matches[0]!.metadata as Record<string, unknown>);
    }
  }

  return result;
}
