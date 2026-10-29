'use client'

import { Pencil, Trash2 } from 'lucide-react'
import { Fragment, useState, useTransition } from 'react'
import { deleteTrade } from '@/app/(app)/trades'
import { Drawer } from '@/components/Drawer'
import { EditTradeForm } from '@/components/portfolio/TradeForms'
import { useToast } from '@/components/Toast'
import { longDay } from '@/lib/dates'
import { fmtAmount, fmtPrice, fmtQty } from '@/lib/format'
import type { FxRate } from '@/lib/portfolio/lookup'
import type { TradeLine } from '@/lib/portfolio/trade-list'
import { ACCOUNT_LABELS } from '@/lib/portfolio/types'

const LATEST = 10

/** Every buy and sell, newest first, each with Edit and Delete. */
export function TradeList({ lines, rates, today }: { lines: TradeLine[]; rates: FxRate[]; today: string }) {
  const toast = useToast()
  const [all, setAll] = useState(false)
  const [asking, setAsking] = useState<string | null>(null)
  const [editing, setEditing] = useState<TradeLine | null>(null)
  const [pending, startTransition] = useTransition()
  const shown = all ? lines : lines.slice(0, LATEST)

  const remove = (line: TradeLine) =>
    startTransition(async () => {
      const result = await deleteTrade(line.side, line.id)
      setAsking(null)
      if (result.message) toast(result.message)
    })

  return (
    <section className="card card-pad enter" aria-labelledby="trades-h">
      <div className="section-head">
        <h2 id="trades-h">Trades</h2>
        <span className="sub">
          {lines.length} recorded · newest first
        </span>
      </div>
      <div className="table-scroll">
        <table className="data-table" id="trades">
          <thead>
            <tr>
              <th>Date</th>
              <th>Account</th>
              <th>Trade</th>
              <th className="r">Quantity</th>
              <th className="r">Price</th>
              <th className="r">Amount C$</th>
              <th>
                <span className="sr-only">Edit or delete</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((line) => {
              const what = line.side === 'buy' ? 'Buy' : 'Sell'
              return (
                <Fragment key={line.key}>
                <tr>
                  <td className="num t-day">{longDay(line.day)}</td>
                  <td className="sub t-acct">{ACCOUNT_LABELS[line.account]}</td>
                  <td className="t-what">
                    <span className="badge">{what}</span> <span className="sym">{line.symbol}</span>
                  </td>
                  <td className="r num t-qty">{fmtQty(line.qty)}</td>
                  <td className="r num t-price">{fmtPrice(line.price, line.currency)}</td>
                  <td className="r num t-amount">{line.amountCad === null ? '—' : fmtAmount(line.amountCad)}</td>
                  <td className="sub t-meta" aria-hidden="true">
                    {longDay(line.day)} · {ACCOUNT_LABELS[line.account]} · {fmtQty(line.qty)} ×{' '}
                    {fmtPrice(line.price, line.currency)}
                  </td>
                  <td className="t-del">
                    {asking !== line.key && (
                      <div className="trade-actions">
                        <button
                          type="button"
                          className="icon-btn"
                          aria-label={`Edit the ${line.side} of ${fmtQty(line.qty)} ${line.symbol} on ${longDay(line.day)}`}
                          onClick={() => {
                            setAsking(null)
                            setEditing(line)
                          }}
                        >
                          <Pencil />
                        </button>
                        <button
                          type="button"
                          className="icon-btn"
                          aria-label={`Delete the ${line.side} of ${fmtQty(line.qty)} ${line.symbol} on ${longDay(line.day)}`}
                          onClick={() => setAsking(line.key)}
                        >
                          <Trash2 />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
                {asking === line.key && (
                  <tr className="trade-ask">
                    <td colSpan={7} className="t-ask">
                      <div className="trade-confirm" role="group" aria-label={`Delete this ${line.side}?`}>
                        <span className="sub">
                          {line.strandsSells
                            ? `Later sells of ${line.symbol} would then exceed what you held.`
                            : "This can't be undone."}
                        </span>
                        <button type="button" className="btn btn-primary btn-sm" disabled={pending} onClick={() => remove(line)}>
                          {pending ? 'Deleting…' : 'Delete'}
                        </button>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAsking(null)}>
                          Keep
                        </button>
                      </div>
                    </td>
                  </tr>
                )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
      {lines.length > LATEST && (
        <button type="button" className="btn btn-ghost btn-sm" style={{ marginTop: 8 }} onClick={() => setAll((a) => !a)}>
          {all ? `Show the latest ${LATEST}` : `Show all ${lines.length}`}
        </button>
      )}
      <Drawer
        id="edit-trade"
        title={editing?.side === 'sell' ? 'Edit this sell' : 'Edit this buy'}
        open={editing !== null}
        onClose={() => setEditing(null)}
      >
        {editing && (
          <EditTradeForm
            key={editing.key}
            line={editing}
            rates={rates}
            today={today}
            onCancel={() => setEditing(null)}
            onDone={(message) => {
              setEditing(null)
              toast(message)
            }}
          />
        )}
      </Drawer>
    </section>
  )
}
