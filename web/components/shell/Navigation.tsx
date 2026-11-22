'use client'

import { Ellipsis, History, LogOut, Search } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Fragment, useCallback, useState, type MouseEvent } from 'react'
import { signOut } from '@/app/(app)/actions'
import { deviceStorage, readRecent } from '@/lib/recent'
import { tickerHref } from '@/lib/ticker'
import { Drawer } from '../Drawer'
import { ThemeToggle } from '../ThemeToggle'
import { FindTicker } from './FindTicker'
import { NAV, NAV_DIVIDER_BEFORE, isCurrent, type NavItem } from './nav'
import { NavPill, TabPill } from './NavPill'
import { useHideOnScroll } from './useHideOnScroll'

/**
 * Where the pill goes among `items`: the link just tapped, so it slides at once rather than when the next page
 * arrives, otherwise the current page's link; null when none of them is current (a page under More).
 */
function usePillTarget(items: readonly NavItem[]) {
  const pathname = usePathname()
  const [tapped, setTapped] = useState<string | null>(null)
  const [seen, setSeen] = useState(pathname)
  if (seen !== pathname) {
    // The page changed (the tap landed, or Back): the pathname decides again.
    setSeen(pathname)
    setTapped(null)
  }
  const current = items.find((n) => isCurrent(n.href, pathname))?.href ?? null
  const onTap = (href: string) => (event: MouseEvent) => {
    // A new tab or window leaves this page where it is.
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    setTapped(href)
  }
  return { pathname, target: tapped ?? current, onTap }
}

/** The desktop sidebar's pages, with the sliding pill, and Sources and Settings under a divider. */
export function SidebarLinks() {
  const { pathname, target, onTap } = usePillTarget(NAV)
  return (
    <nav className="nav">
      <NavPill target={target} />
      {NAV.map(({ href, label, icon: Icon }) => (
        <Fragment key={href}>
          {href === NAV_DIVIDER_BEFORE && <div className="nav-sep" role="separator" />}
          <Link
            className="nav-link"
            href={href}
            aria-current={isCurrent(href, pathname) ? 'page' : undefined}
            onClick={onTap(href)}
          >
            <Icon />
            {label}
          </Link>
        </Fragment>
      ))}
    </nav>
  )
}

const TABS = NAV.filter((n) => n.tab)
const MORE = NAV.filter((n) => n.group === 'more')

/**
 * The phone's floating tab bar: Today, Portfolio and Day trade, then Search and More, each opening a sheet. The bar
 * slips away while scrolling down and comes back on the way up.
 */
export function BottomTabs() {
  const { pathname, target, onTap } = usePillTarget(TABS)
  const hidden = useHideOnScroll()
  const [more, setMore] = useState(false)
  const [search, setSearch] = useState(false)
  // Each opening gets a fresh, empty search box that takes the focus (and so the keyboard) straight away.
  const [searchKey, setSearchKey] = useState(0)
  // The stocks opened lately on this device, read as the sheet opens (lib/recent.ts); empty without storage.
  const [recent, setRecent] = useState<string[]>([])
  const closeMore = useCallback(() => setMore(false), [])
  const closeSearch = useCallback(() => setSearch(false), [])
  const openSearch = () => {
    setSearchKey((k) => k + 1)
    setRecent(readRecent(deviceStorage()))
    setSearch(true)
  }
  return (
    <>
      <nav
        className={`bottom-tabs ${hidden ? 'hidden' : ''}`}
        aria-label="Main"
        style={{ gridTemplateColumns: `repeat(${TABS.length + 2}, 1fr)` }}
      >
        <TabPill target={target} />
        {TABS.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            className="bottom-tab"
            href={href}
            aria-current={isCurrent(href, pathname) ? 'page' : undefined}
            onClick={onTap(href)}
          >
            <Icon />
            {label}
          </Link>
        ))}
        <button type="button" className="bottom-tab" aria-haspopup="dialog" onClick={openSearch}>
          <Search />
          Search
        </button>
        <button
          type="button"
          className="bottom-tab"
          aria-haspopup="dialog"
          aria-current={MORE.some((n) => isCurrent(n.href, pathname)) ? 'page' : undefined}
          onClick={() => setMore(true)}
        >
          <Ellipsis />
          More
        </button>
      </nav>
      <Drawer id="search-sheet" title="Search" open={search} onClose={closeSearch}>
        <div className="drawer-body">
          {/* The top bar's glass search pill, in a sheet of its own. */}
          <div className="statusbar-search">
            {searchKey > 0 && <FindTicker key={searchKey} onGo={closeSearch} autoFocus />}
          </div>
          {recent.length > 0 && (
            <section className="recent" aria-labelledby="recent-label">
              <h3 id="recent-label" className="label">
                Recent
              </h3>
              <ul>
                {recent.map((symbol) => (
                  <li key={symbol}>
                    {/* A symbol only: the Ticker page works out whether it's a stock or a coin. */}
                    <Link className="nav-link" href={tickerHref(symbol, 'stock')} onClick={closeSearch}>
                      <History aria-hidden="true" />
                      <span className="sym">{symbol}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </Drawer>
      <Drawer id="more-sheet" title="More" open={more} onClose={closeMore}>
        <div className="drawer-body">
          <div style={{ display: 'grid', gap: 2 }}>
            {MORE.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                className="nav-link"
                href={href}
                aria-current={isCurrent(href, pathname) ? 'page' : undefined}
                onClick={closeMore}
              >
                <Icon />
                {label}
              </Link>
            ))}
          </div>
          <div className="more-foot">
            <ThemeToggle />
            {/* Every market is in its paper period until picks are graded live (spec §6.6, Plan 4). */}
            <span className="more-note" title="No picks graded live yet">
              <span className="dot paper" />
              US Paper · TSX Paper
            </span>
            <form action={signOut}>
              <button type="submit" className="btn btn-ghost btn-sm">
                <LogOut />
                Sign out
              </button>
            </form>
          </div>
        </div>
      </Drawer>
    </>
  )
}
