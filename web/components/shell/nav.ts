import { Activity, ChartCandlestick, Eye, History, PiggyBank, Settings, Sparkles, Sun, Wallet, type LucideIcon } from 'lucide-react'

export interface NavItem {
  href: string
  label: string
  icon: LucideIcon
  /** A phone tab; the other pages sit in the More sheet. */
  tab: boolean
  /** On a phone, 'more' pages are in the More sheet. */
  group: 'main' | 'more'
}

/**
 * Every page, in the sidebar's order (spec §6). On a phone the first three are tabs and the rest are under More,
 * in the mockup's order (this supersedes the 2026-11-15 note that put Watchlist first under More). On a desktop,
 * Sources and Settings sit under a divider. History (results and trades, owner request 2026-11-23) follows Day trade.
 * Track record joins with live grading (Plan 4c).
 */
export const NAV: readonly NavItem[] = [
  { href: '/', label: 'Today', icon: Sun, tab: true, group: 'main' },
  { href: '/portfolio', label: 'Portfolio', icon: Wallet, tab: true, group: 'main' },
  { href: '/daytrade', label: 'Day trade', icon: ChartCandlestick, tab: true, group: 'main' },
  { href: '/history', label: 'History', icon: History, tab: false, group: 'more' },
  { href: '/picks', label: 'Picks', icon: Sparkles, tab: false, group: 'more' },
  { href: '/invest', label: 'Invest', icon: PiggyBank, tab: false, group: 'more' },
  { href: '/watchlist', label: 'Watchlist', icon: Eye, tab: false, group: 'more' },
  { href: '/sources', label: 'Sources', icon: Activity, tab: false, group: 'more' },
  { href: '/settings', label: 'Settings', icon: Settings, tab: false, group: 'more' },
]

/** The desktop sidebar draws its divider before this page. */
export const NAV_DIVIDER_BEFORE = '/sources'

export const isCurrent = (href: string, pathname: string): boolean =>
  href === '/' ? pathname === '/' : pathname === href || pathname.startsWith(`${href}/`)
