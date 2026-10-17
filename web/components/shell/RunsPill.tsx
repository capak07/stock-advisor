'use client'

import { ChevronDown } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

export interface RunView {
  id: number
  dot: string
  label: string
  when: string
  status: string
  note: string | null
  sources: string | null
}

/** The latest run in the status bar; it opens the last four runs (spec §9, top bar). */
export function RunsPill({ runs }: { runs: RunView[] }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('click', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('click', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const latest = runs[0]
  if (!latest) {
    return (
      <span className="pill">
        <span className="dot skipped" />
        No runs yet
      </span>
    )
  }
  return (
    <div ref={root} style={{ position: 'relative' }}>
      <button
        type="button"
        className="pill"
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls="runs-pop"
        onClick={() => setOpen((o) => !o)}
      >
        <span className={`dot ${latest.dot}`} />
        {latest.label}
        <span className="muted hide-sm">{latest.status}</span>
        <ChevronDown style={{ width: 14, height: 14 }} />
      </button>
      <div className={`popover ${open ? 'open' : ''}`} id="runs-pop" role="menu" style={{ left: 0, top: 'calc(100% + 6px)' }}>
        <div className="label" style={{ padding: '8px 10px 4px' }}>
          Last runs
        </div>
        {runs.map((r) => (
          <div key={r.id} className="popover-row" role="menuitem">
            <span className={`dot ${r.dot}`} />
            <span>
              <span style={{ fontWeight: 500 }}>{r.when}</span>
              <br />
              <span className="sub">
                {r.status}
                {r.note ? ` · ${r.note}` : ''}
              </span>
            </span>
            <span className="num sub">{r.sources ?? '—'}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
