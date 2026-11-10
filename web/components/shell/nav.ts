import { Activity, ChartCandlestick, Eye, PiggyBank, Settings, Sparkles, Wallet, type LucideIcon } from 'lucide-react'

export interface NavItem {
  href: string
  label: string
  icon: LucideIcon
  /** Primary pages are phone tabs; the rest sit in the More sheet. */
  primary: boolean
}

/** The pages built so far. Track record joins with live grading (Plan 4c). */
export const NAV: readonly NavItem[] = [
  { href: '/', label: 'Portfolio', icon: Wallet, primary: true },
  { href: '/picks', label: 'Picks', icon: Sparkles, primary: true },
  { href: '/watchlist', label: 'Watchlist', icon: Eye, primary: true },
  { href: '/invest', label: 'Invest', icon: PiggyBank, primary: true },
  { href: '/daytrade', label: 'Day trade', icon: ChartCandlestick, primary: true },
  { href: '/sources', label: 'Sources', icon: Activity, primary: false },
  { href: '/settings', label: 'Settings', icon: Settings, primary: false },
]

export const isCurrent = (href: string, pathname: string): boolean =>
  href === '/' ? pathname === '/' : pathname === href || pathname.startsWith(`${href}/`)
