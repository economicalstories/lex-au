/**
 * Integration tests for the MCP JSON-RPC endpoint and REST routes.
 *
 * Uses the Hono app directly (no Cloudflare bindings needed for protocol tests).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import app from "../src/index";
import type { Env } from "../src/env";

// Mock Cloudflare bindings
function createMockEnv(): Env {
  return {
    AI: {
      run: vi.fn().mockResolvedValue({ data: [new Array(1024).fill(0.1)] }),
    } as unknown as Ai,
    LEGISLATION_INDEX: {
      query: vi.fn().mockResolvedValue({ matches: [], count: 0 }),
    } as unknown as VectorizeIndex,
    LEGISLATION_SECTION_INDEX: {
      query: vi.fn().mockResolvedValue({ matches: [], count: 0 }),
    } as unknown as VectorizeIndex,
    RATE_LIMITER: {
      limit: vi.fn().mockResolvedValue({ success: true }),
    } as unknown as RateLimit,
  };
}

function jsonRpcRequest(method: string, params?: Record<string, unknown>, id: number = 1) {
  return {
    jsonrpc: "2.0" as const,
    id,
    method,
    params,
  };
}

describe("Health endpoint", () => {
  it("GET /health returns 200", async () => {
    const env = createMockEnv();
    const res = await app.request("/health", {}, env);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.status).toBe("ok");
    expect(body.service).toBe("lex-au");
  });
});

describe("MCP protocol", () => {
  let env: Env;

  beforeEach(() => {
    env = createMockEnv();
  });

  it("POST /mcp initialize returns server info", async () => {
    const res = await app.request(
      "/mcp",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(jsonRpcRequest("initialize")),
      },
      env,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.jsonrpc).toBe("2.0");
    expect(body.id).toBe(1);
    expect(body.result.protocolVersion).toBe("2025-03-26");
    expect(body.result.serverInfo.name).toBe("lex-au");
    expect(body.result.capabilities.tools).toBeDefined();
  });

  it("POST /mcp tools/list returns 5 tools", async () => {
    const res = await app.request(
      "/mcp",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(jsonRpcRequest("tools/list")),
      },
      env,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    const tools = body.result.tools;
    expect(tools.length).toBe(5);

    const names = tools.map((t: { name: string }) => t.name);
    expect(names).toContain("search_for_au_legislation_acts");
    expect(names).toContain("search_for_au_legislation_sections");
    expect(names).toContain("lookup_au_legislation");
    expect(names).toContain("get_au_legislation_sections");
    expect(names).toContain("get_au_legislation_full_text");
  });

  it("POST /mcp tools/call invokes search_for_au_legislation_acts", async () => {
    const res = await app.request(
      "/mcp",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          jsonRpcRequest("tools/call", {
            name: "search_for_au_legislation_acts",
            arguments: { query: "privacy" },
          }),
        ),
      },
      env,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.result.content).toBeDefined();
    expect(body.result.content[0].type).toBe("text");

    // The mock returns empty matches, so result should be parseable JSON
    const parsed = JSON.parse(body.result.content[0].text);
    expect(parsed.results).toEqual([]);
  });

  it("POST /mcp tools/call invokes search_for_au_legislation_sections", async () => {
    const res = await app.request(
      "/mcp",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          jsonRpcRequest("tools/call", {
            name: "search_for_au_legislation_sections",
            arguments: { query: "tax deductions" },
          }),
        ),
      },
      env,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.result.content[0].type).toBe("text");
  });

  it("POST /mcp unknown method returns error", async () => {
    const res = await app.request(
      "/mcp",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(jsonRpcRequest("unknown/method")),
      },
      env,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.error).toBeDefined();
    expect(body.error.code).toBe(-32603);
  });

  it("POST /mcp notification (no id) returns empty", async () => {
    const res = await app.request(
      "/mcp",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jsonrpc: "2.0",
          method: "notifications/initialized",
        }),
      },
      env,
    );
    expect(res.status).toBe(200);
  });
});

describe("REST endpoints", () => {
  let env: Env;

  beforeEach(() => {
    env = createMockEnv();
  });

  it("POST /legislation/search requires query", async () => {
    const res = await app.request(
      "/legislation/search",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
      env,
    );
    expect(res.status).toBe(400);
  });

  it("POST /legislation/search returns results", async () => {
    const res = await app.request(
      "/legislation/search",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: "employment law" }),
      },
      env,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.results).toBeDefined();
    expect(body.total).toBeDefined();
  });

  it("POST /legislation/section/search returns results", async () => {
    const res = await app.request(
      "/legislation/section/search",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: "data protection" }),
      },
      env,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.results).toBeDefined();
  });

  it("POST /legislation/lookup requires all fields", async () => {
    const res = await app.request(
      "/legislation/lookup",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "act" }),
      },
      env,
    );
    expect(res.status).toBe(400);
  });

  it("POST /legislation/section/lookup requires legislation_id", async () => {
    const res = await app.request(
      "/legislation/section/lookup",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
      env,
    );
    expect(res.status).toBe(400);
  });

  it("POST /legislation/text requires legislation_id", async () => {
    const res = await app.request(
      "/legislation/text",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
      env,
    );
    expect(res.status).toBe(400);
  });

  it("GET /nonexistent returns 404", async () => {
    const res = await app.request("/nonexistent", {}, env);
    expect(res.status).toBe(404);
  });
});

describe("Rate limiting", () => {
  it("returns 429 when rate limit exceeded", async () => {
    const env = createMockEnv();
    (env.RATE_LIMITER.limit as ReturnType<typeof vi.fn>).mockResolvedValue({ success: false });

    const res = await app.request(
      "/legislation/search",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: "test" }),
      },
      env,
    );
    expect(res.status).toBe(429);
  });
});
