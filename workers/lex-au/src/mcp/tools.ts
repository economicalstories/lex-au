/**
 * MCP tool definitions and dispatch for AU legislation.
 */

import type { Env } from "../env";
import {
  searchSections,
  searchActs,
  lookupLegislation,
  getSections,
  getFullText,
} from "../vectorize/client";
import {
  parseActSearchInput,
  parseFullTextInput,
  parseLegislationLookupInput,
  parseSectionLookupInput,
  parseSectionSearchInput,
} from "../validation";

export interface McpTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export const TOOLS: McpTool[] = [
  {
    name: "search_for_au_legislation_acts",
    description:
      "Search for Australian federal legislation (Acts and Legislative Instruments) by topic or keyword. Returns ranked results with matching sections.",
    inputSchema: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description: "The search query — a concept, question, or keywords.",
        },
        type: {
          type: "array",
          items: { type: "string", enum: ["act", "li", "ni"] },
          description: "Filter by legislation type (optional).",
        },
        year_from: { type: "integer", description: "Starting year filter (optional)." },
        year_to: { type: "integer", description: "Ending year filter (optional)." },
        limit: { type: "integer", description: "Number of results (default 10)." },
        offset: { type: "integer", description: "Pagination offset (default 0)." },
      },
      required: ["query"],
    },
  },
  {
    name: "search_for_au_legislation_sections",
    description:
      "Search within sections of Australian legislation. Useful for finding specific provisions on a topic, optionally within a single Act.",
    inputSchema: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description: "The search query.",
        },
        legislation_id: {
          type: "string",
          description: "Title ID to search within (e.g., C2004A01386). Optional.",
        },
        type: {
          type: "array",
          items: { type: "string", enum: ["act", "li", "ni"] },
          description: "Filter by legislation type (optional).",
        },
        year_from: { type: "integer", description: "Starting year filter." },
        year_to: { type: "integer", description: "Ending year filter." },
        size: { type: "integer", description: "Number of results (default 10)." },
        offset: { type: "integer", description: "Pagination offset (default 0)." },
      },
      required: ["query"],
    },
  },
  {
    name: "lookup_au_legislation",
    description:
      "Look up a specific Australian Act or instrument by its type, year, and number.",
    inputSchema: {
      type: "object",
      properties: {
        type: {
          type: "string",
          enum: ["act", "li", "ni"],
          description: "Legislation type.",
        },
        year: { type: "integer", description: "The year of the legislation." },
        number: { type: "integer", description: "The legislation number." },
      },
      required: ["type", "year", "number"],
    },
  },
  {
    name: "get_au_legislation_sections",
    description:
      "Get all sections/provisions of a specific Australian Act or instrument.",
    inputSchema: {
      type: "object",
      properties: {
        legislation_id: {
          type: "string",
          description: "The title ID (e.g., C2004A01386).",
        },
        limit: { type: "integer", description: "Max sections to return (default 200)." },
      },
      required: ["legislation_id"],
    },
  },
  {
    name: "get_au_legislation_full_text",
    description:
      "Get the full text structure of an Australian Act or instrument, concatenated from all its sections.",
    inputSchema: {
      type: "object",
      properties: {
        legislation_id: {
          type: "string",
          description: "The title ID (e.g., C2004A01386).",
        },
        include_schedules: {
          type: "boolean",
          description: "Whether to include schedules (default false).",
        },
      },
      required: ["legislation_id"],
    },
  },
];

/** Dispatch an MCP tool call and return the result content. */
export async function dispatchTool(
  env: Env,
  toolName: string,
  args: Record<string, unknown>,
): Promise<unknown> {
  switch (toolName) {
    case "search_for_au_legislation_acts": {
      const input = parseActSearchInput(args);
      if (!input.ok) throw new Error(input.error);

      return searchActs(env, input.value.query, {
        type: input.value.type,
        yearFrom: input.value.year_from,
        yearTo: input.value.year_to,
        limit: input.value.limit,
        offset: input.value.offset,
      });
    }

    case "search_for_au_legislation_sections": {
      const input = parseSectionSearchInput(args);
      if (!input.ok) throw new Error(input.error);

      return searchSections(env, input.value.query, {
        legislationId: input.value.legislation_id,
        type: input.value.type,
        yearFrom: input.value.year_from,
        yearTo: input.value.year_to,
        size: input.value.size,
        offset: input.value.offset,
      });
    }

    case "lookup_au_legislation": {
      const input = parseLegislationLookupInput(args);
      if (!input.ok) throw new Error(input.error);

      return lookupLegislation(
        env,
        input.value.type,
        input.value.year,
        input.value.number,
      );
    }

    case "get_au_legislation_sections": {
      const input = parseSectionLookupInput(args);
      if (!input.ok) throw new Error(input.error);

      return getSections(
        env,
        input.value.legislation_id,
        input.value.limit,
      );
    }

    case "get_au_legislation_full_text": {
      const input = parseFullTextInput(args);
      if (!input.ok) throw new Error(input.error);

      return getFullText(
        env,
        input.value.legislation_id,
        input.value.include_schedules ?? false,
      );
    }

    default:
      throw new Error(`Unknown tool: ${toolName}`);
  }
}
