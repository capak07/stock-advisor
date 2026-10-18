import 'server-only'
import type { Run } from '../runs'
import type { Supabase } from '../supabase/server'
import { must } from './fetch'

const COLUMNS = 'id, kind, et_date, started_at, finished_at, status, published, sources_ok, sources_total, summary'

/** The newest runs, newest first, for the status bar. */
export async function recentRuns(supabase: Supabase, limit = 4): Promise<Run[]> {
  return must(await supabase.from('runs').select(COLUMNS).order('id', { ascending: false }).limit(limit)) as Run[]
}

/** The newest run that published, for the stale banner. */
export async function lastPublishedRun(supabase: Supabase): Promise<Run | null> {
  const rows = must(
    await supabase.from('runs').select(COLUMNS).eq('published', true).order('id', { ascending: false }).limit(1),
  ) as Run[]
  return rows[0] ?? null
}

/** The newest run that finished, published or not, for the Source health page. */
export async function latestFinishedRun(supabase: Supabase): Promise<Run | null> {
  const rows = must(
    await supabase.from('runs').select(COLUMNS).neq('status', 'running').order('id', { ascending: false }).limit(1),
  ) as Run[]
  return rows[0] ?? null
}
