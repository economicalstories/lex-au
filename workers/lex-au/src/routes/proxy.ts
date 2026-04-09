/**
 * Proxy endpoint for legislation.gov.au — fetches live content with 24h cache.
 */

import { Hono } from "hono";
import type { Env } from "../env";
import { parseProxyId } from "../validation";

const AU_WEB_BASE = "https://www.legislation.gov.au";

const proxy = new Hono<{ Bindings: Env }>();

/**
 * GET /proxy/:id — proxy a legislation page from legislation.gov.au.
 *
 * Uses the Cache API to cache responses for 24 hours.
 * The :id param is the title_id (e.g., C2004A01386).
 */
proxy.get("/:id{.+}", async (c) => {
  const parsedId = parseProxyId(c.req.param("id"));
  if (!parsedId.ok) return c.json({ error: parsedId.error }, 400);

  const targetUrl = `${AU_WEB_BASE}/${parsedId.value}`;

  // Check Cloudflare cache
  const cacheKey = new Request(targetUrl);
  const cache = caches.default;
  const cached = await cache.match(cacheKey);
  if (cached) {
    const resp = new Response(cached.body, cached);
    resp.headers.set("X-Cache", "HIT");
    return resp;
  }

  // Fetch from origin
  const response = await fetch(targetUrl, {
    headers: {
      "User-Agent": "lex-au/0.1",
      Accept: "text/html",
    },
    redirect: "follow",
  });

  if (!response.ok) {
    return c.json(
      { error: `Upstream returned ${response.status}` },
      response.status as 404 | 502,
    );
  }

  // Clone and cache with 24h TTL
  const body = await response.arrayBuffer();
  const contentType = response.headers.get("Content-Type") ?? "text/html";

  const cacheResponse = new Response(body, {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Cache-Control": "public, max-age=86400",
      "Access-Control-Allow-Origin": "*",
      "X-Cache": "MISS",
    },
  });

  // Store in cache (non-blocking)
  c.executionCtx.waitUntil(cache.put(cacheKey, cacheResponse.clone()));

  return cacheResponse;
});

export { proxy };
