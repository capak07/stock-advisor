// A stand-in for Yahoo's chart endpoint (lib/intraday.ts, lib/runners-live.ts), so the browser tests never call Yahoo.
// 5-minute bars: every symbol gets the same morning, Mon 2026-11-23 from 9:30 to 10:30 New York time, 13 bars rising
// from 100 to 112 after a previous close of 100; a `.TO` stock or a `-CAD` coin is in CAD, anything else in USD.
// Daily bars (`interval=1d`, the runners): the 30 weekdays up to the last one before today in Toronto, each opening at
// 1.40 (high 1.50, low 1.30, close 1.45), in USD. So a runner signal on the last weekday has no bar after it yet, and
// one on the weekday before has exactly one, closed. NOPE fails.
import { createServer } from 'node:http'

const OPEN = 1795444200 // 2026-11-23 9:30 New York time
const CLOSE = OPEN + 390 * 60
const DAY_MS = 86_400_000

/** The 30 weekdays before today in Toronto, oldest first, as epoch seconds at 15:00 UTC (inside the New York day). */
function weekdayStamps() {
  const today = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Toronto' })
  const stamps = []
  for (let t = Date.parse(`${today}T12:00:00Z`) - DAY_MS; stamps.length < 30; t -= DAY_MS) {
    const weekday = new Date(t).getUTCDay()
    if (weekday !== 0 && weekday !== 6) stamps.unshift(Math.floor(t / 1000) + 3 * 3600) // 15:00 UTC: the New York day
  }
  return stamps
}

function daily() {
  const times = weekdayStamps()
  const bars = (v) => times.map(() => v)
  return {
    chart: {
      result: [
        {
          meta: { currency: 'USD', regularMarketTime: times.at(-1) + 6 * 3600 },
          timestamp: times,
          indicators: { quote: [{ open: bars(1.4), high: bars(1.5), low: bars(1.3), close: bars(1.45) }] },
        },
      ],
    },
  }
}

createServer((req, res) => {
  const symbol = decodeURIComponent(new URL(req.url, 'http://stub').pathname.split('/').pop() ?? '')
  if (symbol === 'health') return res.end('ok')
  if (symbol === 'NOPE') {
    res.statusCode = 500
    return res.end()
  }
  if (new URL(req.url, 'http://stub').searchParams.get('interval') === '1d') {
    res.setHeader('content-type', 'application/json')
    return res.end(JSON.stringify(daily()))
  }
  const times = Array.from({ length: 13 }, (_, i) => OPEN + i * 300)
  const body = {
    chart: {
      result: [
        {
          meta: {
            currency: /\.TO$|-CAD$/.test(symbol) ? 'CAD' : 'USD',
            chartPreviousClose: 100,
            tradingPeriods: [[{ start: OPEN, end: CLOSE }]],
          },
          timestamp: times,
          indicators: { quote: [{ close: times.map((_, i) => 100 + i) }] },
        },
      ],
    },
  }
  res.setHeader('content-type', 'application/json')
  res.end(JSON.stringify(body))
}).listen(3101, '127.0.0.1')
