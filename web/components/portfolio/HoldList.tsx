'use client'

import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { LowRankChip } from '@/components/LowRankChip'

export interface HoldLine {
  key: string
  symbol: string
  name: string | null
  text: string
  /** The exit plan's status note ("Not validated yet…"), shown under the line; null for a passed plan or none. */
  note: string | null
  /** Low model rank in the latest run: how many US stocks it ranked; null when not flagged. */
  lowRank: number | null
}

/** The plain Holds, folded under one toggle below the action cards. */
export function HoldList({ lines }: { lines: HoldLine[] }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        className="hold-toggle"
        aria-expanded={open}
        aria-controls="hold-list"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="chip hold">Hold</span>
        <span style={{ flex: 1, fontSize: 13 }}>
          {lines.length} {lines.length === 1 ? 'holding' : 'holdings'} ·{' '}
          <span className="muted">{lines.map((l) => l.symbol).join(', ')}</span>
        </span>
        <ChevronDown />
      </button>
      <div className={open ? 'expand open' : 'expand'} id="hold-list" inert={!open}>
        <div>
          <div className="card" style={{ marginTop: 8 }}>
            {lines.map((l) => (
              <div className="hold-row" key={l.key}>
                <span>
                  <span className="sym">{l.symbol}</span> {l.name && <span className="sub">{l.name}</span>}
                  {l.lowRank !== null && (
                    <>
                      {' '}
                      <LowRankChip scored={l.lowRank} />
                    </>
                  )}
                </span>
                <span className="num sub">{l.text}</span>
                {l.note && <span className="sub hold-note">{l.note}</span>}
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
