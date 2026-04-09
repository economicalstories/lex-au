/**
 * Tests for score fusion logic.
 */

import { describe, it, expect } from "vitest";
import { fuseScores } from "../src/vectorize/fusion";

describe("fuseScores", () => {
  it("returns empty for empty inputs", () => {
    expect(fuseScores([], [])).toEqual([]);
  });

  it("handles dense-only items", () => {
    const dense = [
      { id: "a", score: 0.9 },
      { id: "b", score: 0.5 },
    ];
    const result = fuseScores(dense, []);
    expect(result.length).toBe(2);
    expect(result[0]!.id).toBe("a");
    expect(result[0]!.score).toBeGreaterThan(result[1]!.score);
  });

  it("handles sparse-only items", () => {
    const sparse = [
      { id: "x", score: 0.8 },
      { id: "y", score: 0.3 },
    ];
    const result = fuseScores([], sparse);
    expect(result.length).toBe(2);
    expect(result[0]!.id).toBe("x");
  });

  it("merges overlapping items with correct weighting", () => {
    const dense = [
      { id: "a", score: 1.0 },
      { id: "b", score: 0.5 },
    ];
    const sparse = [
      { id: "b", score: 1.0 },
      { id: "c", score: 0.5 },
    ];

    const result = fuseScores(dense, sparse);

    // All three IDs should appear
    const ids = result.map((r) => r.id);
    expect(ids).toContain("a");
    expect(ids).toContain("b");
    expect(ids).toContain("c");

    // "a" has dense=1.0, sparse=0 → score = (1.0*3 + 0*0.8)/3.8
    // "b" has dense=(0.5-0.5)/(1-0.5)=0, sparse=1.0 → fused = (0*3 + 1*0.8)/3.8
    // Actually: dense normalised: a=1.0, b=0.0; sparse normalised: b=1.0, c=0.0
    const aScore = result.find((r) => r.id === "a")!.score;
    const bScore = result.find((r) => r.id === "b")!.score;

    // "a" has only dense contribution (weight 3), "b" has only sparse (weight 0.8)
    // so "a" should score higher
    expect(aScore).toBeGreaterThan(bScore);
  });

  it("returns sorted by score descending", () => {
    const dense = [
      { id: "a", score: 0.3 },
      { id: "b", score: 0.9 },
      { id: "c", score: 0.6 },
    ];
    const result = fuseScores(dense, []);
    for (let i = 1; i < result.length; i++) {
      expect(result[i]!.score).toBeLessThanOrEqual(result[i - 1]!.score);
    }
  });

  it("handles single-element lists", () => {
    const dense = [{ id: "solo", score: 0.7 }];
    const result = fuseScores(dense, []);
    expect(result.length).toBe(1);
    // Single element normalises to 1.0
    expect(result[0]!.score).toBeGreaterThan(0);
  });
});
