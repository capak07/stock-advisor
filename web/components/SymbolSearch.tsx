'use client'

import { useId, useState, type KeyboardEvent, type ReactNode } from 'react'
import { searchList } from '@/app/(app)/search'
import { fromRows, highlight, isExactTicker, searchSymbols, type SearchItem } from '@/lib/symbol-search'

// One list for every search box on the page, asked for the first time one is focused. A failed
// load is forgotten, so the next focus tries again.
let list: Promise<SearchItem[]> | null = null
const loadList = (): Promise<SearchItem[]> =>
  (list ??= searchList().then(fromRows, (error: unknown) => {
    list = null
    throw error
  }))

interface Props {
  /** The input's accessible name. */
  label: string
  placeholder: string
  /** Drawn before the input, inside the box (the Find box's magnifier). */
  icon?: ReactNode
  className?: string
  invalid?: boolean
  /** Shown under the box when nothing matches. */
  emptyText: string
  /** Why an item can't be picked (it's watched already, say), shown in place of its tag. */
  unavailable?: (item: SearchItem) => string | null
  onPick: (item: SearchItem) => void
  /** The ticker as typed, for a last row that opens it when no item has that exact ticker; null for no row. */
  typedTicker?: (query: string) => string | null
  /** Enter with nothing to pick, or the typed-ticker row; `ready` is false while the list is still loading. */
  onNoMatch?: (query: string, ready: boolean) => void
  /** The owner typed: callers clear their errors. */
  onEdit?: () => void
}

type Option = { item: SearchItem } | { typed: string }

/**
 * A search box with a list of matching stocks and coins under it (ARIA combobox): best match
 * first, the typed part of the name in bold, and each item's market. Arrows move, Enter picks the
 * highlighted row, Escape closes the list. Picking clears the box.
 *
 * The first row that can be picked is highlighted, except when a ticker is both a stock and a
 * coin (LINK, say): then Enter asks the owner to choose rather than guess.
 */
export function SymbolSearch(props: Props) {
  const { label, placeholder, icon, className, invalid, emptyText, unavailable, onPick, typedTicker, onNoMatch, onEdit } = props
  const id = useId()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  // The row the owner moved to with the arrows or the mouse since the last edit; null when untouched.
  const [moved, setMoved] = useState<number | null>(null)
  const [hint, setHint] = useState<string | null>(null)
  const [items, setItems] = useState<SearchItem[] | null>(null)
  const [failed, setFailed] = useState(false)

  const results = items ? searchSymbols(items, query) : []
  const typed = query.trim() && !results.some((item) => isExactTicker(item, query)) ? (typedTicker?.(query) ?? null) : null
  const options: Option[] = [...results.map((item) => ({ item })), ...(typed ? [{ typed }] : [])]
  const pickable = (option: Option) => !('item' in option) || !unavailable?.(option.item)
  const ambiguous = results.length > 1 && results[0].symbol === results[1].symbol && isExactTicker(results[0], query)
  const current =
    moved !== null && moved < options.length && pickable(options[moved])
      ? moved
      : ambiguous
        ? -1
        : options.findIndex(pickable)
  const showing = open && query.trim() !== ''

  const load = () => {
    if (items) return
    setFailed(false)
    loadList().then(setItems, () => setFailed(true))
  }

  const choose = (option: Option) => {
    if (!pickable(option)) return
    setQuery('')
    setOpen(false)
    setMoved(null)
    setHint(null)
    if ('item' in option) onPick(option.item)
    else onNoMatch?.(option.typed, true)
  }

  // The next row that can be picked, going round; from no highlight, the first or the last.
  const step = (by: 1 | -1) => {
    const n = options.length
    let i = current
    for (let k = 0; k < n; k++) {
      i = i < 0 ? (by === 1 ? 0 : n - 1) : (i + by + n) % n
      if (pickable(options[i])) return setMoved(i)
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (options.length === 0) return
      event.preventDefault()
      setOpen(true)
      setHint(null)
      step(event.key === 'ArrowDown' ? 1 : -1)
    } else if (event.key === 'Enter') {
      event.preventDefault()
      if (!query.trim()) return
      if (current >= 0) choose(options[current])
      else if (ambiguous) setHint(`${results[0].symbol} is both a stock and a coin. Pick one with the arrows or a click.`)
      else if (options.length === 0) onNoMatch?.(query, items !== null)
    } else if (event.key === 'Escape' && showing) {
      // The list closes; a drawer the box sits in stays open.
      event.preventDefault()
      event.stopPropagation()
      setOpen(false)
    }
  }

  let status: string | null = null
  if (showing && options.length === 0) status = items ? emptyText : failed ? "The lists didn't load. Click away and back to try again." : 'Loading the lists…'
  const note = hint ?? status

  return (
    <div className={`combo ${className ?? ''}`}>
      {icon}
      <input
        className="input num-input"
        role="combobox"
        aria-label={label}
        aria-expanded={showing && options.length > 0}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        aria-activedescendant={showing && current >= 0 ? `${id}-${current}` : undefined}
        aria-invalid={invalid || undefined}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        enterKeyHint="go"
        value={query}
        onFocus={() => {
          load()
          setOpen(true)
        }}
        onBlur={() => setOpen(false)}
        onChange={(e) => {
          setQuery(e.target.value)
          setMoved(null)
          setHint(null)
          setOpen(true)
          onEdit?.()
        }}
        onKeyDown={onKeyDown}
      />
      <div className="combo-list" hidden={!showing || (options.length === 0 && !note)}>
        <ul id={`${id}-list`} role="listbox" aria-label={label} hidden={options.length === 0}>
          {options.map((option, i) => {
            const why = 'item' in option ? (unavailable?.(option.item) ?? null) : null
            return (
              <li
                key={'item' in option ? `${option.item.assetType}:${option.item.symbol}` : 'typed'}
                id={`${id}-${i}`}
                role="option"
                aria-selected={i === current}
                aria-disabled={why ? true : undefined}
                className={`combo-row ${i === current ? 'active' : ''} ${'typed' in option ? 'typed' : ''}`}
                // Keep the focus in the box, so the click lands before the list closes.
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => pickable(option) && setMoved(i)}
                onClick={() => choose(option)}
              >
                {'item' in option ? (
                  <>
                    <span className="sym">{option.item.symbol}</span>
                    <span className="combo-name">
                      {highlight(option.item.name, query).map((part, j) => (part.match ? <b key={j}>{part.text}</b> : part.text))}
                    </span>
                    <span className="combo-tag label">{why ?? option.item.kind}</span>
                  </>
                ) : (
                  <>
                    <span className="sym">{option.typed}</span>
                    <span className="combo-name">Open as a symbol</span>
                    <span />
                  </>
                )}
              </li>
            )
          })}
        </ul>
        {note && (
          <p className="combo-note sub" aria-hidden="true">
            {note}
          </p>
        )}
      </div>
      {/* Always there, so screen readers announce the note when it appears. */}
      <p className="sr-only" aria-live="polite">
        {showing ? (note ?? '') : ''}
      </p>
    </div>
  )
}
