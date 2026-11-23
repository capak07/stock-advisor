// A stand-in for Yahoo's chart endpoint (lib/intraday.ts), so the browser tests never call Yahoo. Every symbol gets
// the same morning: Mon 2026-11-23 from 9:30 to 10:30 New York time, 13 five-minute bars rising from 100 to 112 after
// a previous close of 100; a `.TO` stock or a `-CAD` coin is in CAD, anything else in USD. NOPE fails.
import { createServer } from 'node:http'

const OPEN = 1795444200 // 2026-11-23 9:30 New York time
const CLOSE = OPEN + 390 * 60

createServer((req, res) => {
  const symbol = decodeURIComponent(new URL(req.url, 'http://stub').pathname.split('/').pop() ?? '')
  if (symbol === 'health') return res.end('ok')
  if (symbol === 'NOPE') {
    res.statusCode = 500
    return res.end()
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
