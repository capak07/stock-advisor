import 'server-only'
import type { AssetType, Market } from '../portfolio/types'
import type { Run } from '../runs'
import { sourceRows, type Category, type Health, type Source, type SourceRow, type SourceStatus } from '../sources'
import type { Supabase } from '../supabase/server'
import { must } from './fetch'
import { latestFinishedRun } from './runs'

interface HealthRow {
  source: string
  status: SourceStatus
  latency_ms: number
  records: number
  error: string | null
  consecutive_failures: number
  attempted_at: string
}

const HEALTH_COLUMNS = 'source, status, latency_ms, records, error, consecutive_failures, attempted_at'

const toHealth = (r: HealthRow): Health => ({
  source: r.source,
  status: r.status,
  latencyMs: r.latency_ms,
  records: r.records,
  error: r.error,
  failures: r.consecutive_failures,
  attemptedAt: r.attempted_at,
})

/** Each daily check writes one row per source, so a month of checks reaches every source's newest. */
const CHECK_ROWS = 1000

export interface SourceHealth {
  /** The newest finished run; its rows are the "This run" column. */
  run: Run | null
  rows: SourceRow[]
  /** When the newest daily check ran. */
  checkedAt: string | null
}

/** The registry, with each source's latest run result, newest daily check and last good answer. */
export async function loadSourceHealth(supabase: Supabase): Promise<SourceHealth> {
  const [registry, run, checks, lastOk] = await Promise.all([
    supabase.from('sources').select('name, category, core, cadence, asset_types, markets').order('name'),
    latestFinishedRun(supabase),
    supabase
      .from('source_health')
      .select(HEALTH_COLUMNS)
      .eq('context', 'health')
      .order('attempted_at', { ascending: false })
      .limit(CHECK_ROWS),
    supabase.from('source_last_ok').select('source, attempted_at'),
  ])
  const runRows = run
    ? (must(
        await supabase.from('source_health').select(HEALTH_COLUMNS).eq('context', 'run').eq('run_id', run.id),
      ) as HealthRow[])
    : []
  const sources = (
    must(registry) as {
      name: string
      category: Category
      core: boolean
      cadence: Source['cadence']
      asset_types: AssetType[]
      markets: Market[]
    }[]
  ).map((r) => ({ name: r.name, category: r.category, core: r.core, cadence: r.cadence, assetTypes: r.asset_types, markets: r.markets }))
  const checkRows = (must(checks) as HealthRow[]).map(toHealth)
  return {
    run,
    rows: sourceRows(
      sources,
      runRows.map(toHealth),
      checkRows,
      new Map((must(lastOk) as { source: string; attempted_at: string }[]).map((r) => [r.source, r.attempted_at])),
    ),
    checkedAt: checkRows[0]?.attemptedAt ?? null,
  }
}

/** The database's size in bytes; null when Postgres won't say (anyone but the owner). */
export async function databaseSize(supabase: Supabase): Promise<number | null> {
  const size = must(await supabase.rpc('database_size')) as number | string | null
  return size === null ? null : Number(size)
}
