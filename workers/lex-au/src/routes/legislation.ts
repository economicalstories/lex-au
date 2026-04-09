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

const legislation = new Hono<{ Bindings: Env }>();

/** POST /legislation/section/search — semantic section search. */
legislation.post("/section/search", async (c) => {
  const body = await c.req.json();
  const query = body.query as string;
  if (!query) return c.json({ error: "query is required" }, 400);

  const result = await searchSections(c.env, query, {
    legislationId: body.legislation_id,
    type: body.type,
    yearFrom: body.year_from,
    yearTo: body.year_to,
    size: body.size ?? 10,
    offset: body.offset ?? 0,
  });

  return c.json(result);
});

/** POST /legislation/search — search acts via section embeddings. */
legislation.post("/search", async (c) => {
  const body = await c.req.json();
  const query = body.query as string;
  if (!query) return c.json({ error: "query is required" }, 400);

  const result = await searchActs(c.env, query, {
    type: body.type,
    yearFrom: body.year_from,
    yearTo: body.year_to,
    limit: body.limit ?? 10,
    offset: body.offset ?? 0,
  });

  return c.json(result);
});

/** POST /legislation/lookup — exact lookup by type, year, number. */
legislation.post("/lookup", async (c) => {
  const body = await c.req.json();
  const { type, year, number } = body;
  if (!type || year === undefined || number === undefined) {
    return c.json({ error: "type, year, and number are required" }, 400);
  }

  const result = await lookupLegislation(c.env, type, year, number);
  if (!result) {
    return c.json({ error: `Legislation not found: ${type} ${year} No. ${number}` }, 404);
  }

  return c.json(result);
});

/** POST /legislation/section/lookup — get all sections of a legislation. */
legislation.post("/section/lookup", async (c) => {
  const body = await c.req.json();
  const legislationId = body.legislation_id as string;
  if (!legislationId) {
    return c.json({ error: "legislation_id is required" }, 400);
  }

  const sections = await getSections(c.env, legislationId, body.limit ?? 200);
  if (sections.length === 0) {
    return c.json({ error: `No sections found for: ${legislationId}` }, 404);
  }

  return c.json(sections);
});

/** POST /legislation/text — get full text of a legislation. */
legislation.post("/text", async (c) => {
  const body = await c.req.json();
  const legislationId = body.legislation_id as string;
  if (!legislationId) {
    return c.json({ error: "legislation_id is required" }, 400);
  }

  const result = await getFullText(
    c.env,
    legislationId,
    body.include_schedules ?? false,
  );

  if (!result) {
    return c.json({ error: `Legislation not found: ${legislationId}` }, 404);
  }

  return c.json(result);
});

export { legislation };
