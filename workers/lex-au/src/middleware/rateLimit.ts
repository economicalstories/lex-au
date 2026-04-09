/**
 * Rate limiting middleware using Cloudflare's native rate limiting binding.
 */

import type { Context, Next } from "hono";
import type { Env } from "../env";

/**
 * Hono middleware that enforces rate limits using the RATE_LIMITER binding.
 *
 * The binding is configured in wrangler.toml:
 *   simple = { limit = 100, period = 60 }
 *
 * Key is derived from the client IP (CF-Connecting-IP header).
 */
export async function rateLimit(
  c: Context<{ Bindings: Env }>,
  next: Next,
): Promise<Response | void> {
  const limiter = c.env.RATE_LIMITER;

  // Use client IP as the rate limit key
  const ip = c.req.header("CF-Connecting-IP") ?? "unknown";
  const { success } = await limiter.limit({ key: ip });

  if (!success) {
    return c.json(
      { error: "Rate limit exceeded. Please try again later." },
      429,
    );
  }

  await next();
}
