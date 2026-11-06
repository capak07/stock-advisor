/** `metrics.config.policy.top_n` from an active model. Missing, null, or not a positive integer is today's P floor. */
export function topNOf(metrics: unknown): number | null {
  const policy = (metrics as { config?: { policy?: { top_n?: unknown } | null } } | null)?.config?.policy
  const n = policy?.top_n
  return typeof n === 'number' && Number.isInteger(n) && n > 0 ? n : null
}
