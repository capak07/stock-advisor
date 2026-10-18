'use client'

import { FileSpreadsheet, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useState, useTransition } from 'react'
import { importTrades, unlistedStocks } from '@/app/(app)/import'
import { Drawer } from '@/components/Drawer'
import { longDay } from '@/lib/dates'
import { fmtPrice, fmtQty } from '@/lib/format'
import { parseCsv } from '@/lib/import/csv'
import {
  MEANINGS,
  guessMeanings,
  meaningProblems,
  readRows,
  type DateOrder,
  type ImportRow,
  type Meaning,
} from '@/lib/import/rows'
import { ACCOUNTS, ACCOUNT_LABELS } from '@/lib/portfolio/types'
import type { Account, Trade } from '@/lib/portfolio/types'
import { tradeCurrency } from '@/lib/symbols'

type Step = 'file' | 'columns' | 'review'
const STEPS: { step: Step; label: string }[] = [
  { step: 'file', label: '1 · File' },
  { step: 'columns', label: '2 · Columns' },
  { step: 'review', label: '3 · Review' },
]
const SHOWN = 50

interface Loaded {
  name: string
  rows: string[][]
}

const STATUS: Record<ImportRow['status'] | 'unlisted', string> = {
  ready: 'Ready',
  duplicate: 'Duplicate',
  skipped: 'Left out',
  error: 'Error',
  unlisted: 'Not in the lists',
}

/**
 * Import a broker's activity file (spec §7.1, the mockup's three steps): pick the CSV, say what
 * each column means, review every row, then add the ready ones in one go.
 */
function ImportForm({
  existing,
  rateFrom,
  today,
  onDone,
}: {
  existing: Trade[]
  rateFrom: string | null
  today: string
  onDone: (m: string) => void
}) {
  const [step, setStep] = useState<Step>('file')
  const [file, setFile] = useState<Loaded | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [meanings, setMeanings] = useState<Meaning[]>([])
  const [account, setAccount] = useState<Account | 'column'>('tfsa')
  const [dateOrder, setDateOrder] = useState<DateOrder>('ymd')
  const [unlisted, setUnlisted] = useState<string[] | null>(null)
  const [includeUnlisted, setIncludeUnlisted] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [pending, startTransition] = useTransition()

  const load = async (picked: File | undefined) => {
    setFileError(null)
    if (!picked) return
    const rows = parseCsv(await picked.text())
    if (rows.length < 2) {
      setFileError('That file has no rows under its header.')
      return
    }
    const guessed = guessMeanings(rows[0])
    setFile({ name: picked.name, rows })
    setMeanings(guessed)
    setAccount(guessed.includes('account') ? 'column' : 'tfsa')
    setStep('columns')
  }

  const problems = file ? meaningProblems(meanings, account === 'column') : []
  const read = useMemo(
    () =>
      file && step === 'review'
        ? readRows(file.rows, { meanings, account: account === 'column' ? null : account, dateOrder, today, existing, rateFrom })
        : [],
    [file, step, meanings, account, dateOrder, today, existing, rateFrom],
  )
  const readySymbols = useMemo(
    () => [...new Set(read.filter((r) => r.status === 'ready' && r.trade?.assetType === 'stock').map((r) => r.trade!.symbol))],
    [read],
  )

  // The review asks the server which stock symbols aren't in the lists.
  useEffect(() => {
    if (step !== 'review') return
    let live = true
    unlistedStocks(readySymbols).then((found) => {
      if (live) setUnlisted(found)
    })
    return () => {
      live = false
    }
  }, [step, readySymbols])

  const isUnlisted = (r: ImportRow) => r.status === 'ready' && r.trade?.assetType === 'stock' && (unlisted ?? []).includes(r.trade.symbol)
  const toImport = read.filter((r) => r.status === 'ready' && (includeUnlisted || !isUnlisted(r)))
  const counts = {
    ready: toImport.length,
    unlisted: read.filter(isUnlisted).length,
    duplicate: read.filter((r) => r.status === 'duplicate').length,
    skipped: read.filter((r) => r.status === 'skipped').length,
    error: read.filter((r) => r.status === 'error').length,
  }

  const submit = () =>
    startTransition(async () => {
      setMessage(null)
      const result = await importTrades(toImport.map((r) => r.trade!))
      if (result.ok && result.message) onDone(result.message)
      else setMessage(result.message ?? 'Nothing was imported.')
    })

  return (
    <>
      <div className="drawer-body">
        <div className="flex flex-wrap gap-2 sub">
          {STEPS.map((s) => (
            <span key={s.step} className={`badge ${s.step === step ? 'badge-current' : ''}`} aria-current={s.step === step ? 'step' : undefined}>
              {s.label}
            </span>
          ))}
        </div>

        {step === 'file' && (
          <>
            <label className={`field ${fileError ? 'invalid' : ''}`}>
              <span>Activity file (CSV)</span>
              <input className="input" type="file" accept=".csv,text/csv" onChange={(e) => load(e.target.files?.[0])} />
              <span className="hint">Export your activity from the broker as CSV, for example in Wealthsimple: Activity → Export.</span>
              <span className="error">{fileError}</span>
            </label>
          </>
        )}

        {step !== 'file' && file && (
          <div className="card card-pad" style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <FileSpreadsheet style={{ width: 18, height: 18 }} />
            <span style={{ flex: 1 }}>
              <span style={{ fontWeight: 500 }}>{file.name}</span>
              <br />
              <span className="sub">{file.rows.length - 1} rows</span>
            </span>
          </div>
        )}

        {step === 'columns' && file && (
          <>
            <span className="label">Match the columns</span>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>In the file</th>
                    <th>Means</th>
                    <th>Example</th>
                  </tr>
                </thead>
                <tbody>
                  {file.rows[0].map((header, i) => (
                    <tr key={i}>
                      <td className="num">{header || `Column ${i + 1}`}</td>
                      <td>
                        <select
                          className="select"
                          aria-label={`What "${header}" means`}
                          value={meanings[i]}
                          onChange={(e) => setMeanings((m) => m.map((x, j) => (j === i ? (e.target.value as Meaning) : x)))}
                        >
                          {MEANINGS.map((m) => (
                            <option key={m.value} value={m.value}>
                              {m.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="num sub">{file.rows[1][i] ?? ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label className="field">
                <span>Account</span>
                <select className="select" value={account} onChange={(e) => setAccount(e.target.value as Account | 'column')}>
                  <option value="column">From the Account column</option>
                  {ACCOUNTS.map((a) => (
                    <option key={a} value={a}>
                      All {ACCOUNT_LABELS[a]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Dates like 03/10/2026 are</span>
                <select className="select" value={dateOrder} onChange={(e) => setDateOrder(e.target.value as DateOrder)}>
                  <option value="ymd">Year, month, day</option>
                  <option value="mdy">Month/day/year</option>
                  <option value="dmy">Day/month/year</option>
                </select>
              </label>
            </div>
            {problems.length > 0 && (
              <div className="banner warn" role="alert">
                <TriangleAlert />
                <div>{problems.join(' ')}</div>
              </div>
            )}
          </>
        )}

        {step === 'review' && (
          <>
            <p className="sub" style={{ margin: 0 }}>
              <b className="num">{counts.ready}</b> ready to import
              {counts.unlisted > 0 && ` · ${counts.unlisted} not in the stock lists`}
              {counts.duplicate > 0 && ` · ${counts.duplicate} already recorded or repeated`}
              {counts.skipped > 0 && ` · ${counts.skipped} not ${counts.skipped === 1 ? 'a trade' : 'trades'}`}
              {counts.error > 0 && ` · ${counts.error} with errors`}
            </p>
            {counts.unlisted > 0 && (
              <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
                <input type="checkbox" checked={includeUnlisted} onChange={(e) => setIncludeUnlisted(e.target.checked)} />
                Import the {counts.unlisted} not in the lists too (ETFs aren&apos;t listed)
              </label>
            )}
            {message && (
              <div className="banner danger" role="alert">
                <TriangleAlert />
                <div>{message}</div>
              </div>
            )}
            <div className="table-scroll">
              <table className="data-table" id="import-rows">
                <thead>
                  <tr>
                    <th>Line</th>
                    <th>Trade</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {read.slice(0, SHOWN).map((r) => {
                    const status = isUnlisted(r) ? 'unlisted' : r.status
                    const t = r.trade
                    return (
                      <tr key={r.line}>
                        <td className="num sub">{r.line}</td>
                        <td>
                          {t ? (
                            <>
                              {t.side === 'buy' ? 'Buy' : 'Sell'} {fmtQty(t.qty)} <span className="sym">{t.symbol}</span>
                              <br />
                              <span className="sub">
                                {ACCOUNT_LABELS[t.account]} · {longDay(t.day)} · {fmtPrice(t.price, tradeCurrency(t.assetType, t.symbol))}
                              </span>
                            </>
                          ) : (
                            <span className="sub">{r.reason}</span>
                          )}
                        </td>
                        <td>
                          <span className="badge">{STATUS[status]}</span>
                          {t && r.reason && (
                            <>
                              <br />
                              <span className="sub">{r.reason}</span>
                            </>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            {read.length > SHOWN && <p className="sub" style={{ margin: 0 }}>The first {SHOWN} of {read.length} rows are shown.</p>}
          </>
        )}
      </div>
      <div className="drawer-foot">
        {step === 'columns' && (
          <>
            <button type="button" className="btn btn-secondary" onClick={() => setStep('file')}>
              Back
            </button>
            <button type="button" className="btn btn-primary" disabled={problems.length > 0} onClick={() => { setUnlisted(null); setStep('review') }}>
              Review {file ? file.rows.length - 1 : 0} rows
            </button>
          </>
        )}
        {step === 'review' && (
          <>
            <button type="button" className="btn btn-secondary" onClick={() => setStep('columns')}>
              Back
            </button>
            <button type="button" className="btn btn-primary" disabled={pending || unlisted === null || counts.ready === 0} onClick={submit}>
              {pending ? 'Importing…' : `Import ${counts.ready} ${counts.ready === 1 ? 'trade' : 'trades'}`}
            </button>
          </>
        )}
      </div>
    </>
  )
}

/** The drawer around the import form. Each opening starts afresh. */
export function ImportDrawer({
  open,
  round,
  existing,
  rateFrom,
  today,
  onClose,
  onDone,
}: {
  open: boolean
  round: number
  existing: Trade[]
  /** The earliest day with a stored USD/CAD rate, or null when none is stored. */
  rateFrom: string | null
  today: string
  onClose: () => void
  onDone: (message: string) => void
}) {
  return (
    <Drawer id="import-drawer" title="Import a file" open={open} onClose={onClose}>
      <ImportForm key={round} existing={existing} rateFrom={rateFrom} today={today} onDone={onDone} />
    </Drawer>
  )
}
