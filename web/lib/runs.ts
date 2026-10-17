/** How the status bar and its banners describe pipeline runs (spec §9, top bar). */

import { shortDay } from './dates'

export type RunKind = 'pre_open' | 'pre_close' | 'early_close'
export type RunStatus = 'running' | 'success' | 'degraded' | 'failed'

/** The columns of a `runs` row the dashboard reads. */
export interface Run {
  id: number
  kind: RunKind
  et_date: string
  started_at: string
  finished_at: string | null
  status: RunStatus
  published: boolean
  sources_ok: number | null
  sources_total: number | null
  summary: { failed_reason?: string[] } & Record<string, unknown>
}

export const KIND_LABEL: Record<RunKind, string> = {
  pre_open: 'Pre-open',
  pre_close: 'Pre-close',
  early_close: 'Early close',
}

/** The dot classes of ledger.css for each status. */
export const STATUS_DOT: Record<RunStatus, string> = {
  success: 'ok',
  degraded: 'partial',
  failed: 'failed',
  running: 'ok running',
}

const clock = new Intl.DateTimeFormat('en-CA', {
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
  timeZone: 'America/Toronto',
})

/** When the run finished (or started, while it runs), on Toronto's clock: "15:31". */
export const runTime = (run: Run): string => clock.format(new Date(run.finished_at ?? run.started_at))

/** "Pre-close 15:31" */
export const runLabel = (run: Run): string => `${KIND_LABEL[run.kind]} ${runTime(run)}`

/** "Oct 16 · pre-close 15:31" */
export const runWhen = (run: Run): string =>
  `${shortDay(run.et_date)} · ${KIND_LABEL[run.kind].toLowerCase()} ${runTime(run)}`

/** "30/33", or null for a run that hasn't counted its sources yet. */
export const runSources = (run: Run): string | null =>
  run.sources_ok === null || run.sources_total === null ? null : `${run.sources_ok}/${run.sources_total}`

export interface Notice {
  title: string
  detail: string
}

/**
 * The stale banner: shown when the newest finished run failed, so the dashboard is showing an
 * older run's results (spec §9). `runs` is newest first.
 */
export function staleNotice(runs: readonly Run[], lastPublished: Run | null): Notice | null {
  const latest = runs.find((r) => r.status !== 'running')
  if (!latest || latest.status !== 'failed') return null
  const reasons = latest.summary.failed_reason ?? []
  const why = reasons.length > 0 ? `${reasons.join('; ')}.` : 'See the run summary.'
  const showing = lastPublished
    ? `Showing the ${runWhen(lastPublished)} results until the next run.`
    : 'No run has published yet.'
  return { title: `The ${runWhen(latest)} run failed:`, detail: `${why} ${showing}` }
}
