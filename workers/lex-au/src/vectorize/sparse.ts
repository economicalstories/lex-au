/**
 * BM25 sparse vector hashing — must produce identical output to
 * src/lex_au/core/embeddings.py (djb2_hash, tokenize_for_sparse, build_sparse_vector).
 */

const SPARSE_DIMENSIONS = 30_000;

/** Matches Python: re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?") */
const TOKEN_RE = /[a-z0-9]+(?:'[a-z0-9]+)?/g;

/**
 * djb2 hash over UTF-8 bytes of a token, masked to uint32.
 * Must match Python:
 *   value = 5381
 *   for byte in token.encode("utf-8"):
 *       value = ((value << 5) + value + byte) & 0xFFFFFFFF
 */
export function djb2Hash(token: string): number {
  const encoder = new TextEncoder();
  const bytes = encoder.encode(token);
  let value = 5381;
  for (const byte of bytes) {
    // (value << 5) + value  ===  value * 33
    value = ((value << 5) + value + byte) & 0xffffffff;
  }
  // Ensure non-negative result (>>> 0 interprets as unsigned)
  return value >>> 0;
}

/** NFKC normalise + lowercase, then extract tokens. */
export function tokenize(text: string): string[] {
  const normalised = text.normalize("NFKC").toLowerCase();
  return Array.from(normalised.matchAll(TOKEN_RE), (m) => m[0]);
}

export interface SparseVector {
  indices: number[];
  values: number[];
}

/** Build a sparse TF vector from text (matches Python build_sparse_vector). */
export function buildSparseVector(
  text: string,
  dimensions: number = SPARSE_DIMENSIONS,
): SparseVector {
  const tokens = tokenize(text);
  if (tokens.length === 0) {
    return { indices: [], values: [] };
  }

  const counts = new Map<number, number>();
  for (const token of tokens) {
    const idx = djb2Hash(token) % dimensions;
    counts.set(idx, (counts.get(idx) ?? 0) + 1);
  }

  const indices = Array.from(counts.keys()).sort((a, b) => a - b);
  const total = tokens.length;
  const values = indices.map((idx) => (counts.get(idx) ?? 0) / total);

  return { indices, values };
}
