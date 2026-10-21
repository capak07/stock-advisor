'use client'

import { useId, useState, type KeyboardEvent, type ReactNode } from 'react'
import { searchList } from '@/app/(app)/search'
import { highlight, searchSymbols, type SearchItem } from '@/lib/symbol-search'

// One list for every search box on the page, asked for the first time one is focused. A failed
// load is forgotten, so the next focus tries again.
let list: Promise<SearchItem[]> | null = null
const loadList = (): Promise<SearchItem[]> =>
  (list ??= searchList().catch((error: unknown) => {
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
  /** Shown in the list when nothing matches. */
  emptyText: string
  /** Why an item can't be picked (it's watched already, say), shown in place of its tag. */
  unavailable?: (item: SearchItem) => string | null
  onPick: (item: SearchItem) => void
  /** Enter with nothing in the list to pick; `ready` is false while the list is still loading. */
  onNoMatch?: (query: string, ready: boolean) => void
  /** The owner typed: callers clear their errors. */
  onEdit?: () => void
}

/**
 * A search box with a list of matching stocks and coins under it (ARIA combobox): best match
 * first, the typed part of the name in bold, and each item's market. Arrows move, Enter picks the
 * highlighted item, Escape closes the list. Picking clears the box.
 */
export function SymbolSearch({ label, placeholder, icon, className, invalid, emptyText, unavailable, onPick, onNoMatch, onEdit }: Props) {
  const id = useId()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [items, setItems] = useState<SearchItem[] | null>(null)
  const [failed, setFailed] = useState(false)

  const results = items ? searchSymbols(items, query) : []
  const current = Math.min(active, results.length - 1)
  const showing = open && query.trim() !== ''

  const load = () => {
    if (items) return
    setFailed(false)
    loadList().then(setItems, () => setFailed(true))
  }

  const pick = (item: SearchItem) => {
    if (unavailable?.(item)) return
    setQuery('')
    setOpen(false)
    onPick(item)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (results.length === 0) return
      event.preventDefault()
      setOpen(true)
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActive((current + step + results.length) % results.length)
    } else if (event.key === 'Enter') {
      event.preventDefault()
      if (!query.trim()) return
      if (results.length > 0) pick(results[current])
      else onNoMatch?.(query, items !== null)
    } else if (event.key === 'Escape' && showing) {
      event.preventDefault()
      setOpen(false)
    }
  }

  let status: string | null = null
  if (showing && results.length === 0) status = items ? emptyText : failed ? "The lists didn't load. Click away and back to try again." : 'Loading the lists…'

  return (
    <div className={`combo ${className ?? ''}`}>
      {icon}
      <input
        className="input num-input"
        role="combobox"
        aria-label={label}
        aria-expanded={showing && results.length > 0}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        aria-activedescendant={showing && results.length > 0 ? `${id}-${current}` : undefined}
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
          setActive(0)
          setOpen(true)
          onEdit?.()
        }}
        onKeyDown={onKeyDown}
      />
      <ul id={`${id}-list`} role="listbox" aria-label={label} className="combo-list" hidden={!showing || results.length === 0}>
        {results.map((item, i) => {
          const why = unavailable?.(item) ?? null
          return (
            <li
              key={`${item.assetType}:${item.symbol}`}
              id={`${id}-${i}`}
              role="option"
              aria-selected={i === current}
              aria-disabled={why ? true : undefined}
              className={`combo-row ${i === current ? 'active' : ''}`}
              // Keep the focus in the box, so the click lands before the list closes.
              onMouseDown={(e) => e.preventDefault()}
              onMouseEnter={() => setActive(i)}
              onClick={() => pick(item)}
            >
              <span className="sym">{item.symbol}</span>
              <span className="combo-name">
                {highlight(item.name, query).map((part, j) => (part.match ? <b key={j}>{part.text}</b> : part.text))}
              </span>
              <span className="combo-tag label">{why ?? item.kind}</span>
            </li>
          )
        })}
      </ul>
      {status && (
        <div className="combo-list combo-empty sub" aria-live="polite">
          {status}
        </div>
      )}
    </div>
  )
}
