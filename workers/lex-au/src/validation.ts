/**
 * Input validation and abuse-prevention guardrails for public Worker routes.
 */

import type { Context } from "hono";
import type { Env } from "./env";
import type {
  ActSearchInput,
  AULegislationType,
  FullTextInput,
  LegislationLookupInput,
  SectionLookupInput,
  SectionSearchInput,
} from "./types";

const VALID_TYPES = new Set<AULegislationType>(["act", "li", "ni"]);
const MIN_YEAR = 1900;
const MAX_YEAR = new Date().getUTCFullYear() + 1;

export const MAX_JSON_BODY_BYTES = 16 * 1024;
export const MAX_MCP_BODY_BYTES = 32 * 1024;
export const MAX_QUERY_LENGTH = 500;
export const MAX_SEARCH_LIMIT = 20;
export const MAX_OFFSET = 100;
export const MAX_SECTION_LOOKUP_LIMIT = 100;
export const MAX_PROXY_ID_LENGTH = 160;

type ValidationResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string; status?: number };

const encoder = new TextEncoder();

export async function parseJsonBody<T>(
  c: Context<{ Bindings: Env }>,
  maxBytes: number,
): Promise<{ ok: true; data: T } | { ok: false; response: Response }> {
  const contentLength = c.req.header("Content-Length");
  if (contentLength) {
    const size = Number.parseInt(contentLength, 10);
    if (Number.isFinite(size) && size > maxBytes) {
      return {
        ok: false,
        response: c.json(
          { error: `Request body too large. Maximum size is ${maxBytes} bytes.` },
          413,
        ),
      };
    }
  }

  let rawBody = "";
  try {
    rawBody = await c.req.text();
  } catch {
    return {
      ok: false,
      response: c.json({ error: "Unable to read request body." }, 400),
    };
  }

  if (!rawBody.trim()) {
    return {
      ok: false,
      response: c.json({ error: "Request body is required." }, 400),
    };
  }

  if (encoder.encode(rawBody).byteLength > maxBytes) {
    return {
      ok: false,
      response: c.json(
        { error: `Request body too large. Maximum size is ${maxBytes} bytes.` },
        413,
      ),
    };
  }

  try {
    return { ok: true, data: JSON.parse(rawBody) as T };
  } catch {
    return {
      ok: false,
      response: c.json({ error: "Invalid JSON body." }, 400),
    };
  }
}

export function parseActSearchInput(input: unknown): ValidationResult<ActSearchInput> {
  if (!isRecord(input)) return invalid("JSON body must be an object.");

  const query = normalizeQuery(input.query);
  if (!query) return invalid(`query is required and must be at most ${MAX_QUERY_LENGTH} characters.`);

  const yearFrom = normalizeOptionalYear(input.year_from, "year_from");
  if (!yearFrom.ok) return yearFrom;

  const yearTo = normalizeOptionalYear(input.year_to, "year_to");
  if (!yearTo.ok) return yearTo;

  if (
    yearFrom.value !== undefined &&
    yearTo.value !== undefined &&
    yearFrom.value > yearTo.value
  ) {
    return invalid("year_from cannot be greater than year_to.");
  }

  return {
    ok: true,
    value: {
      query,
      type: normalizeTypes(input.type),
      year_from: yearFrom.value,
      year_to: yearTo.value,
      limit: clampInteger(input.limit, 10, 1, MAX_SEARCH_LIMIT),
      offset: clampInteger(input.offset, 0, 0, MAX_OFFSET),
    },
  };
}

export function parseSectionSearchInput(input: unknown): ValidationResult<SectionSearchInput> {
  if (!isRecord(input)) return invalid("JSON body must be an object.");

  const query = normalizeQuery(input.query);
  if (!query) return invalid(`query is required and must be at most ${MAX_QUERY_LENGTH} characters.`);

  const legislationId = normalizeLegislationId(input.legislation_id);
  if (input.legislation_id !== undefined && !legislationId) {
    return invalid("legislation_id is invalid.");
  }

  const yearFrom = normalizeOptionalYear(input.year_from, "year_from");
  if (!yearFrom.ok) return yearFrom;

  const yearTo = normalizeOptionalYear(input.year_to, "year_to");
  if (!yearTo.ok) return yearTo;

  if (
    yearFrom.value !== undefined &&
    yearTo.value !== undefined &&
    yearFrom.value > yearTo.value
  ) {
    return invalid("year_from cannot be greater than year_to.");
  }

  return {
    ok: true,
    value: {
      query,
      legislation_id: legislationId ?? undefined,
      type: normalizeTypes(input.type),
      year_from: yearFrom.value,
      year_to: yearTo.value,
      size: clampInteger(input.size, 10, 1, MAX_SEARCH_LIMIT),
      offset: clampInteger(input.offset, 0, 0, MAX_OFFSET),
    },
  };
}

export function parseLegislationLookupInput(
  input: unknown,
): ValidationResult<LegislationLookupInput> {
  if (!isRecord(input)) return invalid("JSON body must be an object.");

  const type = normalizeType(input.type);
  if (!type) return invalid("type must be one of: act, li, ni.");

  const year = normalizeRequiredInteger(input.year);
  if (year === undefined || year < MIN_YEAR || year > MAX_YEAR) {
    return invalid(`year must be an integer between ${MIN_YEAR} and ${MAX_YEAR}.`);
  }

  const number = normalizeRequiredInteger(input.number);
  if (number === undefined || number < 0 || number > 100000) {
    return invalid("number must be a non-negative integer.");
  }

  return {
    ok: true,
    value: { type, year, number },
  };
}

export function parseSectionLookupInput(input: unknown): ValidationResult<SectionLookupInput> {
  if (!isRecord(input)) return invalid("JSON body must be an object.");

  const legislationId = normalizeLegislationId(input.legislation_id);
  if (!legislationId) return invalid("legislation_id is required.");

  return {
    ok: true,
    value: {
      legislation_id: legislationId,
      limit: clampInteger(input.limit, MAX_SECTION_LOOKUP_LIMIT, 1, MAX_SECTION_LOOKUP_LIMIT),
    },
  };
}

export function parseFullTextInput(input: unknown): ValidationResult<FullTextInput> {
  if (!isRecord(input)) return invalid("JSON body must be an object.");

  const legislationId = normalizeLegislationId(input.legislation_id);
  if (!legislationId) return invalid("legislation_id is required.");

  return {
    ok: true,
    value: {
      legislation_id: legislationId,
      include_schedules: Boolean(input.include_schedules),
    },
  };
}

export function parseProxyId(input: unknown): ValidationResult<string> {
  const id = normalizeProxyPath(input);
  if (!id) {
    return invalid("id is required and must be a safe legislation.gov.au path.");
  }
  return { ok: true, value: id };
}

function normalizeOptionalYear(
  value: unknown,
  label: string,
): ValidationResult<number | undefined> {
  if (value === undefined || value === null || value === "") {
    return { ok: true, value: undefined };
  }

  const parsed = normalizeRequiredInteger(value);
  if (parsed === undefined || parsed < MIN_YEAR || parsed > MAX_YEAR) {
    return invalid(`${label} must be an integer between ${MIN_YEAR} and ${MAX_YEAR}.`);
  }

  return { ok: true, value: parsed };
}

function clampInteger(
  value: unknown,
  fallback: number,
  min: number,
  max: number,
): number {
  const parsed = normalizeRequiredInteger(value);
  if (parsed === undefined) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

function normalizeRequiredInteger(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isInteger(value) && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string" && /^-?\d+$/.test(value.trim())) {
    return Number.parseInt(value.trim(), 10);
  }

  return undefined;
}

function normalizeQuery(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > MAX_QUERY_LENGTH) return null;
  return trimmed;
}

function normalizeTypes(value: unknown): AULegislationType[] | undefined {
  if (!Array.isArray(value)) return undefined;

  const types = Array.from(
    new Set(
      value
        .filter((item): item is string => typeof item === "string")
        .map((item) => item.trim())
        .filter((item): item is AULegislationType => VALID_TYPES.has(item as AULegislationType)),
    ),
  );

  return types.length > 0 ? types : undefined;
}

function normalizeType(value: unknown): AULegislationType | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim() as AULegislationType;
  return VALID_TYPES.has(trimmed) ? trimmed : null;
}

function normalizeLegislationId(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > MAX_PROXY_ID_LENGTH) return null;
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(trimmed)) return null;
  return trimmed;
}

function normalizeProxyPath(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > MAX_PROXY_ID_LENGTH) return null;
  if (trimmed.startsWith("/") || trimmed.includes("..") || trimmed.includes("//")) return null;
  if (!/^[A-Za-z0-9][A-Za-z0-9/_.-]*$/.test(trimmed)) return null;
  return trimmed;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function invalid<T>(error: string, status = 400): ValidationResult<T> {
  return { ok: false, error, status };
}
