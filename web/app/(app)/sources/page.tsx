import { TriangleAlert } from 'lucide-react'
import type { Metadata } from 'next'
import { SourceTable, type SourceLine } from '@/components/sources/SourceTable'
import { ownerClient } from '@/lib/auth'
import { databaseSize, loadSourceHealth } from '@/lib/data/sources'
import { timeOrDate } from '@/lib/dates'
import { runWhen } from '@/lib/runs'
import { BREAKER_THRESHOLD, CATEGORY_LABELS, fmtLatency, fmtSize, sentimentNotice, tally, type SourceRow, type Tally } from '@/lib/sources'

export const metadata: Metadata = { title: 'Source health' }

/** Supabase's free plan allows a 500 MB database. */
const FREE_DATABASE_BYTES = 500e6

/** "2 partial · 1 stale · none failed", or "every source answered". */
function details(t: Tally): string {
  const parts = [
    t.partial && `${t.partial} partial`,
    t.stale && `${t.stale} stale`,
    t.skipped && `${t.skipped} skipped`,
    t.missing && `${t.missing} not run`,
  ].filter(Boolean)
  if (parts.length === 0 && t.failed === 0) return 'every source answered'
  return [...parts, t.failed ? `${t.failed} failed` : 'none failed'].join(' · ')
}

/** The breaker follows the source's newest result, in a run or a check. */
function breaker(row: SourceRow): string {
  const newest = [row.run, row.check].filter((h) => h !== null).sort((a, b) => (a.attemptedAt < b.attemptedAt ? 1 : -1))[0]
  const fails = newest?.failures ?? 0
  const state = fails >= BREAKER_THRESHOLD ? 'open' : 'closed'
  return fails === 0 ? state : `${state} · ${fails} ${fails === 1 ? 'fail' : 'fails'} in a row`
}

const line = (row: SourceRow): SourceLine => ({
  name: row.name,
  kind: CATEGORY_LABELS[row.category],
  core: row.core,
  problem: row.problem,
  status: row.run?.status ?? null,
  time: row.run ? fmtLatency(row.run.latencyMs) : '—',
  records: row.run ? row.run.records.toLocaleString('en-CA') : '—',
  recordsMeta: row.run ? `${row.run.records.toLocaleString('en-CA')} ${row.run.records === 1 ? 'record' : 'records'}` : 'not run',
  breaker: breaker(row),
  check: row.check?.status ?? null,
  lastOk: row.lastOk ? timeOrDate(row.lastOk) : 'never',
  errors: [
    row.run?.error && `This run: ${row.run.error}`,
    row.check?.error && `Daily check (${timeOrDate(row.check.attemptedAt)}): ${row.check.error}`,
  ].filter((e): e is string => Boolean(e)),
})

/** Source health (spec §9): every source's latest result, its daily check, and the database's size. */
export default async function SourcesPage() {
  const supabase = await ownerClient()
  if (!supabase) return null // the layout is showing the not-the-owner notice
  const [health, size] = await Promise.all([loadSourceHealth(supabase), databaseSize(supabase)])
  const { rows, run, checkedAt } = health
  const inRun = tally(rows, (r) => r.run)
  const checked = tally(rows, (r) => r.check)
  const core = rows.filter((r) => r.core)
  const coreOk = core.filter((r) => r.run?.status === 'ok').length
  const when = [run && `the ${runWhen(run)} run`, checkedAt && `the daily check at ${timeOrDate(checkedAt)}`].filter(Boolean)
  const sentiment = run ? sentimentNotice(run.summary) : null

  return (
    <main className="page">
      <div className="enter">
        <h1>Source health</h1>
        <p className="sub">
          The {rows.length} keyless sources behind each run{when.length > 0 && ` · from ${when.join(' and ')}`}
        </p>
      </div>
      <section className="summary stagger" aria-label="Summary">
        <div className="card">
          <span className="label">This run</span>
          <b>
            {inRun.ok}
            <span className="muted" style={{ fontSize: 15 }}>
              /{inRun.total} OK
            </span>
          </b>
          <span className="sub">{run ? details(inRun) : 'no run has finished yet'}</span>
        </div>
        <div className="card">
          <span className="label">Daily check</span>
          <b className={checkedAt && checked.ok === checked.total ? 'gain' : undefined}>
            {checked.ok}
            <span className="muted" style={{ fontSize: 15 }}>
              /{checked.total} OK
            </span>
          </b>
          <span className="sub">{checkedAt ? details(checked) : 'no daily check yet'}</span>
        </div>
        <div className="card">
          <span className="label">Core sources</span>
          <b>
            {coreOk}
            <span className="muted" style={{ fontSize: 15 }}>
              /{core.length} OK
            </span>
          </b>
          <span className="sub">a core failure degrades the run</span>
        </div>
        <div className="card">
          <span className="label">Database</span>
          <b>{size === null ? '—' : fmtSize(size)}</b>
          <span className="sub">of Supabase&apos;s free 500 MB</span>
          {size !== null && (
            <div className="usage" role="img" aria-label={`${Math.round((size / FREE_DATABASE_BYTES) * 100)}% used`}>
              <span style={{ width: `${Math.min(100, (size / FREE_DATABASE_BYTES) * 100)}%` }} />
            </div>
          )}
        </div>
      </section>
      {sentiment && (
        <div className="banner warn enter" role="note">
          <TriangleAlert />
          <div>
            <strong>News sentiment:</strong> {sentiment}
          </div>
        </div>
      )}
      <section className="card card-pad enter sources-card">
        {rows.length === 0 ? (
          <p className="sub" style={{ margin: 0 }}>
            No sources yet. The next run or daily check lists them here.
          </p>
        ) : (
          <SourceTable lines={rows.map(line)} />
        )}
      </section>
    </main>
  )
}
