'use client'

import { X } from 'lucide-react'
import { useEffect, useRef, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'

const noop = () => () => {}

/**
 * A sheet from the bottom on phones and a panel from the right on wider screens (ledger.css).
 * Escape and the backdrop close it; focus moves to its first field and back to the opener.
 * It renders into <body>, as in the mockups: inside the page, an animated ancestor's stacking
 * context would put it under the sticky status bar.
 */
export function Drawer({
  id,
  title,
  open,
  onClose,
  children,
}: {
  id: string
  title: string
  open: boolean
  onClose: () => void
  children: React.ReactNode
}) {
  const panel = useRef<HTMLDivElement>(null)
  const opener = useRef<Element | null>(null)
  const mounted = useSyncExternalStore(noop, () => true, () => false)

  useEffect(() => {
    if (!open) return
    opener.current = document.activeElement
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    const timer = setTimeout(() => {
      const first = panel.current?.querySelector<HTMLElement>('input, select, textarea, button:not([data-close])')
      ;(first ?? panel.current)?.focus()
    }, reduce ? 0 : 260)
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => {
      clearTimeout(timer)
      document.removeEventListener('keydown', onKey)
      if (opener.current instanceof HTMLElement) opener.current.focus()
    }
  }, [open, onClose])

  if (!mounted) return null
  return createPortal(
    <>
      <div className={`backdrop ${open ? 'open' : ''}`} onClick={onClose} aria-hidden="true" />
      <div
        ref={panel}
        id={id}
        className={`drawer ${open ? 'open' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-hidden={!open}
        tabIndex={-1}
      >
        <div className="grab" />
        <div className="drawer-head">
          <h2 id={`${id}-title`}>{title}</h2>
          <button type="button" className="icon-btn" data-close aria-label="Close" onClick={onClose}>
            <X />
          </button>
        </div>
        {/* Kept mounted so it doesn't empty while sliding out; a closed drawer is hidden and unfocusable. */}
        {children}
      </div>
    </>,
    document.body,
  )
}
