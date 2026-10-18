'use client'

import { Fragment, useState } from 'react'
import { Tabs } from '@/components/Tabs'

export interface SourceLine {
  name: string
  kind: string
  core: boolean
  problem: boolean
  /** The run's status, or null when the run didn't call it. */
  status: string | null
  time: string
  records: string
  /** The records under the time on phones: "1 record", "5,575 records". */
  recordsMeta: string
  breaker: string
  check: string | null
  lastOk: string
  errors: string[]
}

type Filter = 'all' | 'problems' | 'core'

/** Every source, filterable as in sources_1.html; a problem's errors open under its row. */
export function SourceTable({ lines }: { lines: SourceLine[] }) {
  const [filter, setFilter] = useState<Filter>('all')
  const [open, setOpen] = useState<string | null>(null)
  const problems = lines.filter((l) => l.problem).length
  const core = lines.filter((l) => l.core).length
  const shown = lines.filter((l) => filter === 'all' || (filter === 'problems' ? l.problem : l.core))

  return (
    <>
      <div className="section-head">
        <h2>All sources</h2>
        <Tabs
          items={[
            { value: 'all', label: `All ${lines.length}` },
            { value: 'problems', label: `Problems ${problems}` },
            { value: 'core', label: `Core ${core}` },
          ]}
          value={filter}
          onChange={setFilter}
          label="Show"
        />
      </div>
      <div className="table-scroll">
        <table className="data-table" id="sources">
          <thead>
            <tr>
              <th>Source</th>
              <th>Kind</th>
              <th>This run</th>
              <th className="r">Time</th>
              <th className="r">Records</th>
              <th>Breaker</th>
              <th>Daily check</th>
              <th>Last answered</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((l) => {
              const expanded = open === l.name
              const badge = (
                <>
                  <span className={`dot ${l.status ?? 'skipped'}`} />
                  {l.status ?? 'not run'}
                </>
              )
              return (
                <Fragment key={l.name}>
                  <tr>
                    <td>
                      <span className="sym">{l.name}</span>
                      {l.core && <span className="core">core</span>}
                    </td>
                    <td className="sub">{l.kind}</td>
                    <td>
                      {l.errors.length ? (
                        <button
                          type="button"
                          className="badge"
                          aria-expanded={expanded}
                          aria-controls={`err-${l.name}`}
                          title="Show the error"
                          onClick={() => setOpen(expanded ? null : l.name)}
                        >
                          {badge}
                        </button>
                      ) : (
                        <span className="badge">{badge}</span>
                      )}
                    </td>
                    <td className="r num" data-meta={` · ${l.recordsMeta}`}>
                      {l.time}
                    </td>
                    <td className="r num">{l.records}</td>
                    <td className="sub">{l.breaker}</td>
                    <td>
                      {l.check ? (
                        <span className="badge">
                          <span className={`dot ${l.check}`} />
                          {l.check}
                        </span>
                      ) : (
                        <span className="sub">—</span>
                      )}
                    </td>
                    <td className="sub">{l.lastOk}</td>
                  </tr>
                  {expanded && (
                    <tr className="err" id={`err-${l.name}`}>
                      <td colSpan={8}>
                        {l.errors.map((e) => (
                          <div key={e}>{e}</div>
                        ))}
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="sub" style={{ margin: '12px 0 0' }}>
        &quot;From cache&quot; means the source&apos;s daily or weekly window was still fresh, so the run reused it. A problem&apos;s
        status opens its error. After 3 failures in a row, the breaker skips a source until the next day.
      </p>
    </>
  )
}
