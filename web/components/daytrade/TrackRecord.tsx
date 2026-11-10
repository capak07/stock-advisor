import { TRACK_LABEL, fmtR, recordEmptyLine, type RecordSummary } from '@/lib/daytrade'

function Block({ span, summary: t }: { span: 20 | 60; summary: RecordSummary }) {
  return (
    <div className="kpi dt-record" data-testid={`track-${span}`}>
      <span className="label">
        Last {span} trading days{t.days < span && ` · ${t.days} finished so far`}
      </span>
      <b>
        {t.count} {t.count === 1 ? 'signal' : 'signals'}
      </b>
      <span className="sub num">
        {t.target} target · {t.stop} stop · {t.flat} flat
      </span>
      <span className="sub num">
        {t.avgNetR === null ? 'No net R yet' : `Average ${fmtR(t.avgNetR)}`} · Sum {fmtR(t.sumNetR)}
      </span>
    </div>
  )
}

/** The published top-3 signals' outcomes over the last 20 and 60 finished trading days, after costs. */
export function TrackRecord({ record }: { record: { last20: RecordSummary; last60: RecordSummary } }) {
  const empty = recordEmptyLine(record.last60)
  return (
    <section className="card card-pad enter" aria-labelledby="dt-record-h">
      <div className="section-head" style={{ marginBottom: 4 }}>
        <h2 id="dt-record-h">Track record</h2>
      </div>
      <p className="sub" style={{ margin: '0 0 12px' }}>
        {TRACK_LABEL}
      </p>
      {empty !== null ? (
        <p className="sub" style={{ margin: 0 }}>
          {empty}
        </p>
      ) : (
        <div className="dt-records">
          <Block span={20} summary={record.last20} />
          <Block span={60} summary={record.last60} />
        </div>
      )}
    </section>
  )
}
