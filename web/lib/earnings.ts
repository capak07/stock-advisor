export type Quarter = {
  periodEnd: string
  fiscalPeriod: string | null
  revenue: number | null
  grossProfit: number | null
  operatingIncome: number | null
  netIncome: number | null
  epsDiluted: number | null
}

const DAY_MS = 86_400_000
const daysBetween = (later: string, earlier: string): number => (Date.parse(later) - Date.parse(earlier)) / DAY_MS

/** The quarter whose period end is 365 +/- 10 days before this one (fiscal years drift a few days). */
export const yearAgo = (q: Quarter, all: Quarter[]): Quarter | null => {
  let best: Quarter | null = null
  let bestGap = Infinity
  for (const other of all) {
    const gap = Math.abs(daysBetween(q.periodEnd, other.periodEnd) - 365)
    if (gap <= 10 && gap < bestGap) {
      best = other
      bestGap = gap
    }
  }
  return best
}

const ratio = (part: number | null, revenue: number | null): number | null =>
  part === null || revenue === null || revenue === 0 ? null : part / revenue

export const margins = (q: Quarter): { gross: number | null; operating: number | null; net: number | null } => ({
  gross: ratio(q.grossProfit, q.revenue),
  operating: ratio(q.operatingIncome, q.revenue),
  net: ratio(q.netIncome, q.revenue),
})

type Metric = 'revenue' | 'grossProfit' | 'operatingIncome' | 'netIncome' | 'epsDiluted'
export type Ttm = Record<Metric, number | null>

const METRICS: Metric[] = ['revenue', 'grossProfit', 'operatingIncome', 'netIncome', 'epsDiluted']

const newestFirst = (all: Quarter[]): Quarter[] => [...all].sort((a, b) => Date.parse(b.periodEnd) - Date.parse(a.periodEnd))

/** Sums of the newest four quarters; null unless they are four and span under 300 days. */
export const ttm = (all: Quarter[]): Ttm | null => {
  const four = newestFirst(all).slice(0, 4)
  if (four.length < 4 || daysBetween(four[0].periodEnd, four[3].periodEnd) >= 300) return null
  const out = {} as Ttm
  for (const metric of METRICS) {
    const values = four.map((quarter) => quarter[metric])
    out[metric] = values.some((v) => v === null) ? null : (values as number[]).reduce((a, b) => a + b, 0)
  }
  return out
}

const dollars = (value: number): string => `${value < 0 ? '-' : ''}$${Math.abs(value).toFixed(2)}`

/** Up to three plain sentences on how the newest quarter compares with the same quarter a year earlier. */
export const changes = (all: Quarter[]): string[] => {
  const latest = newestFirst(all)[0]
  const before = latest ? yearAgo(latest, all) : null
  if (!latest || !before) return []
  const out: string[] = []

  if (latest.revenue !== null && before.revenue !== null && before.revenue !== 0 && latest.revenue !== before.revenue) {
    const pct = Math.round((Math.abs(latest.revenue - before.revenue) / Math.abs(before.revenue)) * 100)
    out.push(`Revenue ${latest.revenue > before.revenue ? 'up' : 'down'} ${pct}% on the same quarter a year earlier`)
  }

  const now = margins(latest)
  const then = margins(before)
  for (const [key, label] of [['operating', 'Operating'], ['gross', 'Gross'], ['net', 'Net']] as const) {
    const a = now[key]
    const b = then[key]
    if (a === null || b === null) continue
    const points = (a - b) * 100
    if (Math.abs(points) >= 1) {
      out.push(`${label} margin ${(a * 100).toFixed(1)}%, ${points > 0 ? 'up' : 'down'} ${Math.abs(points).toFixed(1)} points`)
      break
    }
  }

  if (latest.epsDiluted !== null && before.epsDiluted !== null && before.epsDiluted !== 0 && latest.epsDiluted !== before.epsDiluted) {
    out.push(`Diluted EPS ${dollars(latest.epsDiluted)}, ${latest.epsDiluted > before.epsDiluted ? 'up' : 'down'} from ${dollars(before.epsDiluted)}`)
  }
  return out
}
