'use client'

import { Ellipsis } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useCallback, useState } from 'react'
import { Drawer } from '../Drawer'
import { FindTicker } from './FindTicker'
import { NAV, isCurrent } from './nav'

export function SidebarLinks() {
  const pathname = usePathname()
  return (
    <nav style={{ display: 'grid', gap: 2 }}>
      {NAV.map(({ href, label, icon: Icon }) => (
        <Link key={href} className="nav-link" href={href} aria-current={isCurrent(href, pathname) ? 'page' : undefined}>
          <Icon />
          {label}
        </Link>
      ))}
    </nav>
  )
}

/** Phone tabs: the primary pages, then More for the rest. */
export function BottomTabs() {
  const pathname = usePathname()
  const [more, setMore] = useState(false)
  const close = useCallback(() => setMore(false), [])
  const primary = NAV.filter((n) => n.primary)
  const secondary = NAV.filter((n) => !n.primary)
  return (
    <>
      <nav
        className="bottom-tabs"
        aria-label="Main"
        style={{ gridTemplateColumns: `repeat(${primary.length + (secondary.length ? 1 : 0)}, 1fr)` }}
      >
        {primary.map(({ href, label, icon: Icon }) => (
          <Link key={href} className="bottom-tab" href={href} aria-current={isCurrent(href, pathname) ? 'page' : undefined}>
            <Icon />
            {label}
          </Link>
        ))}
        {secondary.length > 0 && (
          <button
            type="button"
            className="bottom-tab"
            aria-current={secondary.some((n) => isCurrent(n.href, pathname)) ? 'page' : undefined}
            onClick={() => setMore(true)}
          >
            <Ellipsis />
            More
          </button>
        )}
      </nav>
      <Drawer id="more-sheet" title="More" open={more} onClose={close}>
        <div className="drawer-body">
          <FindTicker onGo={close} />
          {secondary.map(({ href, label, icon: Icon }) => (
            <Link key={href} className="nav-link" href={href} onClick={close}>
              <Icon />
              {label}
            </Link>
          ))}
        </div>
      </Drawer>
    </>
  )
}
