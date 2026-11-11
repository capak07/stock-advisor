import { COSTS_TITLE, SKILL_TITLE, TRACK_LABEL, fmtR, recordEmptyLine, type RecordSummary, type TrackRecordData } from '@/lib/daytrade'

const DASH = '—'
const r = (value: number | null) => (value === null ? DASH : fmtR(value))

/** One list's figures for a window; a list with no finished trade is a dash row with 0 trades. */
function Row({ name, summary: t }: { name: string; summary: RecordSummary }) {
  const none = t.count === 0
  return (
    <tr>
      <td>{name}</td>
      <td className="r num">{t.count}</td>
      <td className="num">{none ? DASH : `${t.target} / ${t.stop} / ${t.flat}`}</td>
      <td className="r num">{none ? DASH : r(t.avgGrossR)}</td>
      <td className="r num">{none ? DASH : r(t.avgNetR)}</td>
      <td className="r num">{none ? DASH : fmtR(t.sumNetR)}</td>
    </tr>
  )
}

function Window({ span, record }: { span: 20 | 60; record: TrackRecordData }) {
  const skill = span === 20 ? record.skill.last20 : record.skill.last60
  const costs = span === 20 ? record.costs.last20 : record.costs.last60
  const id = `dt-record-${span}`
  return (
    <div className="dt-record" data-testid={`track-${span}`}>
      <p className="sub" id={id} style={{ margin: '0 0 4px' }}>
        Last {span} trading days{skill.days < span && ` · ${skill.days} finished so far`}
      </p>
      <div className="dt-scroll">
        <table className="data-table dt-table" aria-labelledby={id}>
          <thead>
            <tr>
              <th>List</th>
              <th className="r">Trades</th>
              <th>Target / stop / flat</th>
              <th className="r">Average R before costs</th>
              <th className="r">Average R after costs</th>
              <th className="r">Sum after costs</th>
            </tr>
          </thead>
          <tbody>
            <Row name={SKILL_TITLE} summary={skill} />
            <Row name={COSTS_TITLE} summary={costs} />
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** Both lists' finished signals over the last 20 and 60 finished trading days, before and after costs. */
export function TrackRecord({ record }: { record: TrackRecordData }) {
  const empty = recordEmptyLine(record.costs.last60)
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
        <div style={{ display: 'grid', gap: 16 }}>
          <Window span={20} record={record} />
          <Window span={60} record={record} />
        </div>
      )}
    </section>
  )
}
