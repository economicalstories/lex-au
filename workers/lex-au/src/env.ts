/** Cloudflare Worker bindings for lex-au. */

export interface Env {
  /** Vectorize index for legislation-level vectors. */
  LEGISLATION_INDEX: VectorizeIndex;

  /** Vectorize index for section-level vectors. */
  LEGISLATION_SECTION_INDEX: VectorizeIndex;

  /** Workers AI binding for embeddings. */
  AI: Ai;

  /** Rate limiter binding. */
  RATE_LIMITER: RateLimit;
}
