/**
 * Score fusion logic — combines dense and sparse scores.
 *
 * Uses min-max normalisation + weighted sum to approximate DBSF
 * (Distribution-Based Score Fusion) used in the UK Qdrant setup.
 */

export interface ScoredItem {
  id: string;
  denseScore?: number;
  sparseScore?: number;
}

const DENSE_WEIGHT = 3.0;
const SPARSE_WEIGHT = 0.8;

/** Min-max normalise an array of scores to [0, 1]. */
function minMaxNormalise(scores: number[]): number[] {
  if (scores.length === 0) return [];
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const range = max - min;
  if (range === 0) return scores.map(() => 1.0);
  return scores.map((s) => (s - min) / range);
}

/**
 * Fuse dense and sparse scores for a set of items.
 *
 * Items may appear in one or both lists. Missing scores are treated as 0.
 * Returns items sorted by fused score descending.
 */
export function fuseScores(
  denseItems: Array<{ id: string; score: number }>,
  sparseItems: Array<{ id: string; score: number }>,
  denseWeight: number = DENSE_WEIGHT,
  sparseWeight: number = SPARSE_WEIGHT,
): Array<{ id: string; score: number }> {
  // Normalise each list independently
  const normDense = minMaxNormalise(denseItems.map((i) => i.score));
  const normSparse = minMaxNormalise(sparseItems.map((i) => i.score));

  const scoreMap = new Map<string, { dense: number; sparse: number }>();

  denseItems.forEach((item, idx) => {
    scoreMap.set(item.id, {
      dense: normDense[idx] ?? 0,
      sparse: 0,
    });
  });

  sparseItems.forEach((item, idx) => {
    const existing = scoreMap.get(item.id);
    if (existing) {
      existing.sparse = normSparse[idx] ?? 0;
    } else {
      scoreMap.set(item.id, {
        dense: 0,
        sparse: normSparse[idx] ?? 0,
      });
    }
  });

  const totalWeight = denseWeight + sparseWeight;
  const results = Array.from(scoreMap.entries()).map(([id, scores]) => ({
    id,
    score: (scores.dense * denseWeight + scores.sparse * sparseWeight) / totalWeight,
  }));

  results.sort((a, b) => b.score - a.score);
  return results;
}
