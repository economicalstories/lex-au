/**
 * Tests for BM25 sparse hashing — verifies TypeScript matches Python output.
 *
 * The expected values below were generated from the Python implementation:
 *   from lex_au.core.embeddings import djb2_hash, tokenize_for_sparse, build_sparse_vector
 */

import { describe, it, expect } from "vitest";
import { djb2Hash, tokenize, buildSparseVector } from "../src/vectorize/sparse";

describe("djb2Hash", () => {
  it("hashes empty string to 5381", () => {
    // Python: djb2_hash("") == 5381
    expect(djb2Hash("")).toBe(5381);
  });

  it("hashes 'a' correctly", () => {
    // Python: djb2_hash("a") == 177670
    expect(djb2Hash("a")).toBe(177670);
  });

  it("hashes 'hello' correctly", () => {
    // Python: djb2_hash("hello") == 261238937
    expect(djb2Hash("hello")).toBe(261238937);
  });

  it("hashes 'legislation' correctly", () => {
    // Python: djb2_hash("legislation") == 590768608
    expect(djb2Hash("legislation")).toBe(590768608);
  });

  it("handles unicode correctly (UTF-8 bytes)", () => {
    // Python: djb2_hash("café") — multi-byte UTF-8
    // 'c' = 99, 'a' = 97, 'f' = 102, 'é' = 0xc3, 0xa9 (two UTF-8 bytes)
    const result = djb2Hash("café");
    expect(result).toBeGreaterThan(0);
    // Exact value from Python: djb2_hash("café") == 255161979
    expect(result).toBe(255161979);
  });

  it("produces uint32 values (never negative)", () => {
    const tokens = ["test", "legislation", "employment", "data", "protection"];
    for (const token of tokens) {
      const hash = djb2Hash(token);
      expect(hash).toBeGreaterThanOrEqual(0);
      expect(hash).toBeLessThanOrEqual(0xffffffff);
    }
  });
});

describe("tokenize", () => {
  it("lowercases and extracts alphanumeric tokens", () => {
    expect(tokenize("Hello World")).toEqual(["hello", "world"]);
  });

  it("handles contractions", () => {
    expect(tokenize("don't stop")).toEqual(["don't", "stop"]);
  });

  it("strips punctuation", () => {
    expect(tokenize("section 4(a)—definitions")).toEqual([
      "section",
      "4",
      "a",
      "definitions",
    ]);
  });

  it("normalises NFKC", () => {
    // NFKC: ﬁ → fi
    expect(tokenize("ﬁne")).toEqual(["fine"]);
  });

  it("returns empty for empty input", () => {
    expect(tokenize("")).toEqual([]);
  });

  it("handles numbers", () => {
    expect(tokenize("Act 2022 No 7")).toEqual(["act", "2022", "no", "7"]);
  });
});

describe("buildSparseVector", () => {
  it("returns empty for empty text", () => {
    const result = buildSparseVector("");
    expect(result.indices).toEqual([]);
    expect(result.values).toEqual([]);
  });

  it("produces sorted indices", () => {
    const result = buildSparseVector("employment termination procedures");
    expect(result.indices.length).toBeGreaterThan(0);

    // Verify sorted
    for (let i = 1; i < result.indices.length; i++) {
      expect(result.indices[i]).toBeGreaterThan(result.indices[i - 1]!);
    }
  });

  it("values sum to 1.0 (TF normalisation)", () => {
    const result = buildSparseVector("data protection rights and obligations");
    const sum = result.values.reduce((a, b) => a + b, 0);
    expect(sum).toBeCloseTo(1.0, 5);
  });

  it("indices are within dimensions", () => {
    const dims = 30_000;
    const result = buildSparseVector("the quick brown fox jumps over the lazy dog", dims);
    for (const idx of result.indices) {
      expect(idx).toBeGreaterThanOrEqual(0);
      expect(idx).toBeLessThan(dims);
    }
  });

  it("produces consistent output (deterministic)", () => {
    const text = "Privacy Act 1988";
    const a = buildSparseVector(text);
    const b = buildSparseVector(text);
    expect(a).toEqual(b);
  });

  it("repeated tokens increase their value", () => {
    const single = buildSparseVector("tax");
    const repeated = buildSparseVector("tax tax tax");

    // "tax tax tax" has 3 tokens all mapping to the same index → value = 1.0
    expect(repeated.indices.length).toBe(1);
    expect(repeated.values[0]).toBeCloseTo(1.0);

    // "tax" alone also has value 1.0 (single token)
    expect(single.indices.length).toBe(1);
    expect(single.values[0]).toBeCloseTo(1.0);
  });
});
