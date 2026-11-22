'use client'

import { Search } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { SymbolSearch } from '@/components/SymbolSearch'
import { isValidSymbol, normalizeSymbol } from '@/lib/symbols'
import { tickerHref } from '@/lib/ticker'

/** Where the "/" shortcut works: the desktop layout, with the sidebar (ledger.css). */
const DESKTOP = '(min-width: 1024px)'

/** The focus is somewhere typing means something: a field, or a dialog (a sheet) in front of the page. */
const busy = (el: EventTarget | null): boolean =>
  el instanceof HTMLElement && (el.isContentEditable || el.closest('input, textarea, select, [role="dialog"]') !== null)

/**
 * Go to a Ticker page: pick a stock or coin from the list, or the last row that opens a ticker the
 * lists don't have (an ETF like SPY), and the page works out whether it's a stock or a coin.
 *
 * On a desktop, "/" jumps to the box (spec §6). With `autoFocus` the box takes the focus as it appears (the phone's
 * Search sheet).
 */
export function FindTicker({ onGo, autoFocus = false }: { onGo?: () => void; autoFocus?: boolean }) {
  const router = useRouter()
  const box = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!autoFocus) return
    // A frame later, so a sheet opening around the box first notes what had the focus, to give it back on close.
    // Without scrolling: the sheet is still sliding in, and the browser would jump to bring the box into view.
    const frame = requestAnimationFrame(() => box.current?.querySelector('input')?.focus({ preventScroll: true }))
    return () => cancelAnimationFrame(frame)
  }, [autoFocus])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== '/' || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return
      if (!matchMedia(DESKTOP).matches || busy(event.target)) return
      const input = box.current?.querySelector('input')
      // A box in a closed sheet is hidden and leaves the key alone.
      if (!input || (typeof input.checkVisibility === 'function' && !input.checkVisibility({ visibilityProperty: true }))) return
      event.preventDefault()
      input.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const go = (href: string) => {
    setError(null)
    onGo?.()
    router.push(href)
  }

  const asTicker = (query: string): string | null => {
    const symbol = normalizeSymbol(query)
    return isValidSymbol(symbol, 'stock') || isValidSymbol(symbol, 'crypto') ? symbol : null
  }

  const goToTyped = (query: string) => {
    const symbol = asTicker(query)
    if (!symbol) setError('Try a name or a symbol like NVDA, SHOP.TO or BTC.')
    else go(`/ticker/${encodeURIComponent(symbol)}`)
  }

  return (
    <div ref={box} role="search" className={`field ${error ? 'invalid' : ''}`}>
      <SymbolSearch
        label="Find a symbol"
        placeholder="Search any stock…"
        icon={<Search aria-hidden="true" />}
        className="find"
        invalid={error !== null}
        emptyText="No stock or coin matches."
        onPick={(item) => go(tickerHref(item.symbol, item.assetType))}
        typedTicker={asTicker}
        onNoMatch={goToTyped}
        onEdit={() => setError(null)}
      />
      <span className="error">{error}</span>
    </div>
  )
}
