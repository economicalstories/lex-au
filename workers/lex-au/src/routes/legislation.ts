/**
 * REST endpoints for AU legislation search, lookup, and retrieval.
 */

import { Hono } from "hono";
import type { Env } from "../env";
import {
  searchSections,
  searchActs,
  lookupLegislation,
  getSections,
  getFullText,
} from "../vectorize/client";
import {
  MAX_JSON_BODY_BYTES,
  parseActSearchInput,
  parseFullTextInput,
  parseJsonBody,
  parseLegislationLookupInput,
  parseSectionLookupInput,
  parseSectionSearchInput,
} from "../validation";

const legislation = new Hono<{ Bindings: Env }>();

/** POST /legislation/section/search — semantic section search. */
legislation.post("/section/search", async (c) => {
  const parsedBody = await parseJsonBody<Record<string, unknown>>(c, MAX_JSON_BODY_BYTES);
  if (!parsedBody.ok) return parsedBody.response;

  const input = parseSectionSearchInput(parsedBody.data);
  if (!input.ok) return c.json({ error: input.error }, 400);

  const result = await searchSections(c.env, input.value.query, {
    legislationId: input.value.legislation_id,
    type: input.value.type,
    yearFrom: input.value.year_from,
    yearTo: input.value.year_to,
    size: input.value.size,
    offset: input.value.offset,
  });

  return c.json(result);
});

/** POST /legislation/search — search acts via section embeddings. */
legislation.post("/search", async (c) => {
  const parsedBody = await parseJsonBody<Record<string, unknown>>(c, MAX_JSON_BODY_BYTES);
  if (!parsedBody.ok) return parsedBody.response;

  const input = parseActSearchInput(parsedBody.data);
  if (!input.ok) return c.json({ error: input.error }, 400);

  const result = await searchActs(c.env, input.value.query, {
    type: input.value.type,
    yearFrom: input.value.year_from,
    yearTo: input.value.year_to,
    limit: input.value.limit,
    offset: input.value.offset,
  });

  return c.json(result);
});

/** POST /legislation/lookup — exact lookup by type, year, number. */
legislation.post("/lookup", async (c) => {
  const parsedBody = await parseJsonBody<Record<string, unknown>>(c, MAX_JSON_BODY_BYTES);
  if (!parsedBody.ok) return parsedBody.response;

  const input = parseLegislationLookupInput(parsedBody.data);
  if (!input.ok) return c.json({ error: input.error }, 400);

  const result = await lookupLegislation(
    c.env,
    input.value.type,
    input.value.year,
    input.value.number,
  );
  if (!result) {
    return c.json(
      {
        error: `Legislation not found: ${input.value.type} ${input.value.year} No. ${input.value.number}`,
      },
      404,
    );
  }

  return c.json(result);
});

/** POST /legislation/section/lookup — get all sections of a legislation. */
legislation.post("/section/lookup", async (c) => {
  const parsedBody = await parseJsonBody<Record<string, unknown>>(c, MAX_JSON_BODY_BYTES);
  if (!parsedBody.ok) return parsedBody.response;

  const input = parseSectionLookupInput(parsedBody.data);
  if (!input.ok) return c.json({ error: input.error }, 400);

  const sections = await getSections(c.env, input.value.legislation_id, input.value.limit);
  if (sections.length === 0) {
    return c.json({ error: `No sections found for: ${input.value.legislation_id}` }, 404);
  }

  return c.json(sections);
});

/** POST /legislation/text — get full text of a legislation. */
legislation.post("/text", async (c) => {
  const parsedBody = await parseJsonBody<Record<string, unknown>>(c, MAX_JSON_BODY_BYTES);
  if (!parsedBody.ok) return parsedBody.response;

  const input = parseFullTextInput(parsedBody.data);
  if (!input.ok) return c.json({ error: input.error }, 400);

  const result = await getFullText(
    c.env,
    input.value.legislation_id,
    input.value.include_schedules ?? false,
  );

  if (!result) {
    return c.json({ error: `Legislation not found: ${input.value.legislation_id}` }, 404);
  }

  return c.json(result);
});

export { legislation };
