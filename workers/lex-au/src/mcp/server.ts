/**
 * MCP JSON-RPC 2.0 protocol handler.
 *
 * Handles:
 *   - initialize
 *   - tools/list
 *   - tools/call
 *   - notifications/initialized (no-op ack)
 *
 * Implements the Streamable HTTP transport (POST → JSON-RPC response).
 */

import { Hono } from "hono";
import type { Env } from "../env";
import { TOOLS, dispatchTool } from "./tools";
import { MAX_MCP_BODY_BYTES, parseJsonBody } from "../validation";

const MCP_PROTOCOL_VERSION = "2025-03-26";
const SERVER_NAME = "lex-au";
const SERVER_VERSION = "0.1.0";

interface JsonRpcRequest {
  jsonrpc: "2.0";
  id?: string | number | null;
  method: string;
  params?: Record<string, unknown>;
}

interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: string | number | null;
  result?: unknown;
  error?: { code: number; message: string; data?: unknown };
}

const mcp = new Hono<{ Bindings: Env }>();

/** POST /mcp — JSON-RPC 2.0 endpoint. */
mcp.post("/", async (c) => {
  const parsedBody = await parseJsonBody<JsonRpcRequest>(c, MAX_MCP_BODY_BYTES);
  if (!parsedBody.ok) return parsedBody.response;

  const body = parsedBody.data;

  if (body.jsonrpc !== "2.0") {
    return c.json(
      makeError(body.id ?? null, -32600, "Invalid JSON-RPC version"),
    );
  }

  // Notifications (no id) — acknowledge silently
  if (body.id === undefined || body.id === null) {
    // notifications/initialized is the only expected notification
    return c.json({});
  }

  try {
    const result = await handleMethod(c.env, body.method, body.params ?? {});
    return c.json(makeResult(body.id, result));
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return c.json(makeError(body.id, -32603, message));
  }
});

/** GET /mcp — SSE endpoint for server-initiated messages (required by spec). */
mcp.get("/", (c) => {
  // For Streamable HTTP, GET opens an SSE stream.
  // We don't send server-initiated messages, so just keep-alive.
  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const encoder = new TextEncoder();

  // Send an initial comment to establish the SSE connection
  writer.write(encoder.encode(": lex-au MCP server ready\n\n"));

  // Keep the connection open (Cloudflare will close it after 30s idle)
  return new Response(readable, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
});

/** DELETE /mcp — session termination. */
mcp.delete("/", (c) => {
  return c.json({ ok: true });
});

async function handleMethod(
  env: Env,
  method: string,
  params: Record<string, unknown>,
): Promise<unknown> {
  switch (method) {
    case "initialize":
      return {
        protocolVersion: MCP_PROTOCOL_VERSION,
        capabilities: {
          tools: { listChanged: false },
        },
        serverInfo: {
          name: SERVER_NAME,
          version: SERVER_VERSION,
        },
      };

    case "tools/list":
      return {
        tools: TOOLS,
      };

    case "tools/call": {
      const toolName = params.name as string;
      const args = (params.arguments ?? {}) as Record<string, unknown>;
      const result = await dispatchTool(env, toolName, args);

      return {
        content: [
          {
            type: "text",
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    }

    default:
      throw Object.assign(new Error(`Method not found: ${method}`), {
        code: -32601,
      });
  }
}

function makeResult(id: string | number | null, result: unknown): JsonRpcResponse {
  return { jsonrpc: "2.0", id, result };
}

function makeError(
  id: string | number | null,
  code: number,
  message: string,
): JsonRpcResponse {
  return { jsonrpc: "2.0", id, error: { code, message } };
}

export { mcp };
