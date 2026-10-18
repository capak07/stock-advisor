/** Calendar days as ISO strings (`YYYY-MM-DD`), compared as text and shifted in UTC. */

const MS_PER_DAY = 86_400_000

export const addDays = (day: string, days: number): string =>
  new Date(Date.parse(`${day}T00:00:00Z`) + days * MS_PER_DAY).toISOString().slice(0, 10)

export const daysBetween = (from: string, to: string): number =>
  Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / MS_PER_DAY)

/** Today in Toronto, where both markets trade. */
export const todayInToronto = (now: Date = new Date()): string =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Toronto' }).format(now)

/** "Oct 16" */
export const shortDay = (day: string): string =>
  new Date(`${day}T12:00:00Z`).toLocaleDateString('en-CA', { month: 'short', day: 'numeric', timeZone: 'UTC' })

/** "Oct 16, 2026" */
export const longDay = (day: string): string =>
  new Date(`${day}T12:00:00Z`).toLocaleDateString('en-CA', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  })

const clock = new Intl.DateTimeFormat('en-CA', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Toronto' })
const dated = new Intl.DateTimeFormat('en-CA', {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  timeZone: 'America/Toronto',
})

/** A moment on Toronto's clock: "2:53 p.m." today, "Oct 15, 5:53 p.m." on an earlier day. */
export const timeOrDate = (iso: string, now: Date = new Date()): string => {
  const at = new Date(iso)
  return todayInToronto(at) === todayInToronto(now) ? clock.format(at) : dated.format(at)
}
