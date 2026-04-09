/**
 * lex-au — Cloudflare Worker MCP server for Australian federal legislation.
 *
 * Routes:
 *   POST /mcp                        — MCP JSON-RPC endpoint
 *   GET  /mcp                        — MCP SSE stream
 *   POST /legislation/search         — search acts
 *   POST /legislation/section/search — search sections
 *   POST /legislation/lookup         — exact lookup
 *   POST /legislation/section/lookup — sections by legislation_id
 *   POST /legislation/text           — full text
 *   GET  /proxy/:id                  — legislation.gov.au proxy
 *   GET  /health                     — health check
 */

import { Hono } from "hono";
import { cors } from "hono/cors";
import type { Env } from "./env";
import { legislation } from "./routes/legislation";
import { proxy } from "./routes/proxy";
import { mcp } from "./mcp/server";
import { rateLimit } from "./middleware/rateLimit";

const app = new Hono<{ Bindings: Env }>();

// CORS for all routes
app.use("*", cors());

// Small default hardening headers for public API responses.
app.use("*", async (c, next) => {
  await next();
  c.res.headers.set("Referrer-Policy", "no-referrer");
  c.res.headers.set("X-Content-Type-Options", "nosniff");
});

// Rate limiting on API routes (not health check)
app.use("/legislation/*", rateLimit);
app.use("/proxy/*", rateLimit);
app.use("/mcp", rateLimit);
app.use("/mcp/*", rateLimit);

// Mount routes
app.route("/legislation", legislation);
app.route("/proxy", proxy);
app.route("/mcp", mcp);

// Health check
app.get("/health", (c) =>
  c.json({
    status: "ok",
    service: "lex-au",
    version: "0.1.0",
  }),
);

// 404 fallback
app.notFound((c) =>
  c.json({ error: "Not found" }, 404),
);

// Global error handler
app.onError((err, c) => {
  console.error("Unhandled error:", err);
  return c.json(
    { error: err.message ?? "Internal server error" },
    500,
  );
});

export default app;
