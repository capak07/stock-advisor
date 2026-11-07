/** `metrics.config.policy.top_n` from an active model. Missing, null, or not a positive integer is today's P floor. */
export function topNOf(metrics: unknown): number | null {
  const policy = (metrics as { config?: { policy?: { top_n?: unknown } | null } } | null)?.config?.policy
  const n = policy?.top_n
  return typeof n === 'number' && Number.isInteger(n) && n > 0 ? n : null
}

/** `metrics.config.policy.min_edge`: how far q50 must clear costs (spec §11). Missing or invalid is 0. */
export function minEdgeOf(metrics: unknown): number {
  const policy = (metrics as { config?: { policy?: { min_edge?: unknown } | null } } | null)?.config?.policy
  const e = policy?.min_edge
  return typeof e === 'number' && Number.isFinite(e) && e >= 0 && e < 1 ? e : 0
}
