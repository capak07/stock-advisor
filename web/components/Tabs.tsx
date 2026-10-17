'use client'

import { useCallback, useLayoutEffect, useRef, useState } from 'react'

export interface TabItem<T extends string> {
  value: T
  label: string
}

/**
 * The Ledger segmented control: a card-coloured indicator slides under the selected tab (200 ms).
 * The first placement doesn't animate.
 */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  label,
  className = '',
}: {
  items: readonly TabItem<T>[]
  value: T
  onChange: (value: T) => void
  label: string
  className?: string
}) {
  const buttons = useRef(new Map<T, HTMLButtonElement>())
  const [indicator, setIndicator] = useState<{ width: number; x: number; animate: boolean } | null>(null)
  const placed = useRef(false)

  const place = useCallback(
    (animate: boolean) => {
      const button = buttons.current.get(value)
      if (!button) return
      setIndicator({ width: button.offsetWidth, x: button.offsetLeft - 3, animate })
    },
    [value],
  )

  useLayoutEffect(() => {
    place(placed.current)
    placed.current = true
  }, [place])

  useLayoutEffect(() => {
    const again = () => place(false)
    window.addEventListener('resize', again)
    document.fonts?.ready.then(again)
    return () => window.removeEventListener('resize', again)
  }, [place])

  return (
    <div className={`tabs ${className}`} role="tablist" aria-label={label}>
      {indicator && (
        <span
          className="tab-indicator"
          style={{
            left: 3,
            width: indicator.width,
            transform: `translateX(${indicator.x}px)`,
            transition: indicator.animate ? undefined : 'none',
          }}
        />
      )}
      {items.map((item) => (
        <button
          key={item.value}
          ref={(el) => {
            if (el) buttons.current.set(item.value, el)
            else buttons.current.delete(item.value)
          }}
          type="button"
          role="tab"
          className="tab"
          aria-selected={item.value === value}
          onClick={() => onChange(item.value)}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}
