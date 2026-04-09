/** Shared types mirroring AU Python models. */

export type AULegislationType = "act" | "li" | "ni";
export type AUProvisionType = "section" | "schedule";

export interface LegislationMetadata {
  id: string;
  title: string;
  register_id: string;
  type: AULegislationType;
  year: number;
  number: number | null;
  status: string;
  collection: string;
  series_type: string;
  version_label: string;
  compilation_number: string | null;
  administering_departments: string[];
  number_of_provisions: number;
}

export interface SectionMetadata {
  id: string;
  title: string;
  legislation_id: string;
  register_id: string;
  number: string;
  type: AULegislationType;
  year: number;
  legislation_number: number | null;
  provision_type: AUProvisionType;
  chapter: string | null;
  part: string | null;
  division: string | null;
  order: number;
}

/** Search request for sections. */
export interface SectionSearchInput {
  query: string;
  legislation_id?: string;
  type?: AULegislationType[];
  year_from?: number;
  year_to?: number;
  size?: number;
  offset?: number;
}

/** Search request for acts / legislation. */
export interface ActSearchInput {
  query: string;
  type?: AULegislationType[];
  year_from?: number;
  year_to?: number;
  limit?: number;
  offset?: number;
}

/** Exact lookup for a single piece of legislation. */
export interface LegislationLookupInput {
  type: AULegislationType;
  year: number;
  number: number;
}

/** Section lookup by legislation_id. */
export interface SectionLookupInput {
  legislation_id: string;
  limit?: number;
}

/** Full text lookup by legislation_id. */
export interface FullTextInput {
  legislation_id: string;
  include_schedules?: boolean;
}

/** A search result with score. */
export interface ScoredResult<T> {
  metadata: T;
  score: number;
}

/** Paginated response. */
export interface PaginatedResponse<T> {
  results: T[];
  total: number;
  offset: number;
  limit: number;
}
