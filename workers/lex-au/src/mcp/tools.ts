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
    case "search_for_au_legislation_acts":
      return searchActs(env, args.query as string, {
        type: args.type as string[] | undefined,
        yearFrom: args.year_from as number | undefined,
        yearTo: args.year_to as number | undefined,
        limit: (args.limit as number) ?? 10,
        offset: (args.offset as number) ?? 0,
      });

    case "search_for_au_legislation_sections":
      return searchSections(env, args.query as string, {
        legislationId: args.legislation_id as string | undefined,
        type: args.type as string[] | undefined,
        yearFrom: args.year_from as number | undefined,
        yearTo: args.year_to as number | undefined,
        size: (args.size as number) ?? 10,
        offset: (args.offset as number) ?? 0,
      });

    case "lookup_au_legislation":
      return lookupLegislation(
        env,
        args.type as string,
        args.year as number,
        args.number as number,
      );

    case "get_au_legislation_sections":
      return getSections(
        env,
        args.legislation_id as string,
        (args.limit as number) ?? 200,
      );

    case "get_au_legislation_full_text":
      return getFullText(
        env,
        args.legislation_id as string,
        (args.include_schedules as boolean) ?? false,
      );

    default:
      throw new Error(`Unknown tool: ${toolName}`);
  }
}
