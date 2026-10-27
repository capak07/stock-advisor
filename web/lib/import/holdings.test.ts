import { describe, expect, it } from 'vitest'
import { parseCsv } from './csv'
import { isHoldingsReport, readHoldingsReport, type HeldPosition } from './holdings'

// Wealthsimple's holdings report, header as exported (four blank columns before Date); account numbers made up
const HEADER =
  'Account Name,Account Type,Account Classification,Account Number,Symbol,Exchange,MIC,Name,Security Type,Quantity,Position Direction,Market Price,Market Price Currency,Book Value (CAD),Book Value Currency (CAD),Book Value (Market),Book Value Currency (Market),Market Value,Market Value Currency,Market Unrealized Returns,Market Unrealized Returns Currency,,,,Date'
const BONK = 'Crypto,Crypto,Trade,AAAA00000CAD,BONK,,,Bonk,CRYPTOCURRENCY,95934743,LONG,4.28956E-06,CAD,500,CAD,500,CAD,411.3481641,CAD,-88.65183592,CAD,,,,10/27/2026'
const VEEA = 'TFSA,TFSA,Trade,BBBB00000CAD,VEEA,NASDAQ,XNAS,Veea Inc.,EQUITY,118,LONG,6,USD,986.36,CAD,678.4977517,USD,708,USD,29.50224834,USD,,,,10/27/2026'
const XRPN = 'TFSA,TFSA,Trade,BBBB00000CAD,XRPN,NASDAQ,XNAS,Evernorth Holdings Inc.,EQUITY,10.147,LONG,15.115,USD,699.97,CAD,481.6610035,USD,153.371905,USD,-328.2890985,USD,,,,10/27/2026'
const RCI = 'TFSA,TFSA,Trade,BBBB00000CAD,RCI.B,TSX,XTSE,Rogers Communications Inc.,EQUITY,4,LONG,52.10,CAD,200,CAD,200,CAD,208.4,CAD,8.4,CAD,,,,10/27/2026'

const TODAY = '2026-10-27'
const report = (...lines: string[]) => parseCsv([HEADER, ...lines].join('\r\n'))
const read = (lines: string[], held: HeldPosition[] = [], rateFrom: string | null = '2017-01-03') =>
  readHoldingsReport(report(...lines), { today: TODAY, held, rateFrom })
const holding = (p: Partial<HeldPosition> & Pick<HeldPosition, 'account' | 'symbol' | 'qty' | 'costCad'>): HeldPosition => ({
  assetType: p.account === 'crypto' ? 'crypto' : 'stock',
  lastClose: null,
  ...p,
})

describe('isHoldingsReport', () => {
  it("knows Wealthsimple's holdings report by its header", () => {
    expect(isHoldingsReport(parseCsv(HEADER)[0])).toBe(true)
    expect(isHoldingsReport(['Date', 'Activity Type', 'Symbol', 'Quantity', 'Price', 'Account'])).toBe(false)
  })
})

describe('readHoldingsReport', () => {
  it('reads every position as a buy on the report date when nothing is recorded', () => {
    const rows = read([BONK, VEEA, RCI])
    expect(rows.map((r) => [r.line, r.status, r.reason])).toEqual([
      [2, 'ready', 'New position.'],
      [3, 'ready', 'New position.'],
      [4, 'ready', 'New position.'],
    ])
    const [bonk, veea, rci] = rows.map((r) => r.trade!)
    expect(bonk).toMatchObject({ side: 'buy', account: 'crypto', assetType: 'crypto', symbol: 'BONK', qty: 95934743, day: TODAY, fxRate: null })
    expect(bonk.qty * bonk.price).toBeCloseTo(500, 9)
    expect(veea).toMatchObject({ side: 'buy', account: 'tfsa', assetType: 'stock', symbol: 'VEEA', qty: 118, day: TODAY })
    expect(veea.price).toBeCloseTo(678.4977517 / 118, 9)
    expect(veea.fxRate).toBeCloseTo(1.4537, 4) // the book values' own rate: 986.36 / 678.4977517
    expect(veea.qty * veea.price * veea.fxRate!).toBeCloseTo(986.36, 6)
    expect(rci).toMatchObject({ symbol: 'RCI-B.TO', qty: 4, price: 50, fxRate: null })
  })

  it('records a larger position as a buy whose cost is the rise in book value', () => {
    const [row] = read([VEEA], [holding({ account: 'tfsa', symbol: 'VEEA', qty: 100, costCad: 800 })])
    expect([row.status, row.reason]).toEqual(['ready', 'Up from 100.'])
    const t = row.trade!
    expect(t).toMatchObject({ side: 'buy', qty: 18, day: TODAY })
    expect(t.qty * t.price * t.fxRate!).toBeCloseTo(186.36, 6) // so the recorded cost matches 986.36
  })

  it('buys at the market price when the book value did not rise with the quantity', () => {
    const [row] = read([VEEA], [holding({ account: 'tfsa', symbol: 'VEEA', qty: 100, costCad: 1200 })])
    expect(row.status).toBe('ready')
    expect(row.reason).toBe("Up from 100; the book value didn't rise, so at the market price.")
    expect(row.trade).toMatchObject({ side: 'buy', qty: 18, price: 6 })
  })

  it('records a smaller position as a sell at the market price, at the Bank of Canada rate', () => {
    const [row] = read([XRPN], [holding({ account: 'tfsa', symbol: 'XRPN', qty: 20, costCad: 1400 })])
    expect([row.status, row.reason]).toEqual(['ready', 'Down from 20.'])
    expect(row.trade).toMatchObject({ side: 'sell', price: 15.115, fxRate: null, day: TODAY })
    expect(row.trade!.qty).toBeCloseTo(9.853, 9)
  })

  it('sells a position the report no longer lists at its last close, in the accounts the report covers', () => {
    const rows = read(
      [BONK, VEEA],
      [
        holding({ account: 'crypto', symbol: 'ETH', qty: 0.5, costCad: 2000, lastClose: { day: '2026-10-24', close: 5000, currency: 'CAD' } }),
        holding({ account: 'tfsa', symbol: 'GONE', qty: 3, costCad: 90 }),
        holding({ account: 'rrsp', symbol: 'RY.TO', qty: 2, costCad: 300 }), // an account the report doesn't cover
      ],
    )
    expect(rows).toHaveLength(4)
    const [eth, gone] = rows.slice(2)
    expect(eth).toMatchObject({ line: null, status: 'ready' })
    expect(eth.reason).toMatch(/^Not in the report: sold at the last close/)
    expect(eth.trade).toMatchObject({ side: 'sell', account: 'crypto', symbol: 'ETH', qty: 0.5, price: 5000, day: TODAY })
    expect(gone).toMatchObject({ line: null, status: 'error', trade: null })
    expect(gone.reason).toBe('GONE (TFSA) is not in the report and has no stored close: add its sell under Sell.')
  })

  it('adds nothing for a report already recorded', () => {
    const rows = read([BONK, VEEA], [
      holding({ account: 'crypto', symbol: 'BONK', qty: 95934743, costCad: 500 }),
      holding({ account: 'tfsa', symbol: 'VEEA', qty: 118, costCad: 986.36 }),
    ])
    expect(rows.map((r) => [r.status, r.reason, r.trade])).toEqual([
      ['duplicate', 'No change since it was recorded.', null],
      ['duplicate', 'No change since it was recorded.', null],
    ])
  })

  it("refuses a USD sell when no Bank of Canada rate is stored for the report's day", () => {
    const [row] = read([XRPN], [holding({ account: 'tfsa', symbol: 'XRPN', qty: 20, costCad: 1400 })], null)
    expect(row.status).toBe('error')
    expect(row.reason).toMatch(/^No Bank of Canada rate is stored for 2026-10-27/)
  })

  it('explains the rows it cannot read, and never sells a position because its row was unreadable', () => {
    const rows = read(
      [
        VEEA.replace('LONG', 'SHORT'),
        RCI.replace('TSX,XTSE', 'NEO,NEOE'),
        XRPN.replace('10/27/2026', '10/28/2026'),
        BONK.replace('Crypto,Crypto', 'TFSA,TFSA'),
        RCI.replace(',4,', ',lots,'),
        VEEA.replaceAll('VEEA', 'ABCD'),
        VEEA.replaceAll('VEEA', 'ABCD'),
      ],
      [holding({ account: 'tfsa', symbol: 'VEEA', qty: 118, costCad: 986.36 }), holding({ account: 'tfsa', symbol: 'XRPN', qty: 20, costCad: 1400 })],
    )
    expect(rows.map((r) => [r.line, r.status, r.reason])).toEqual([
      [2, 'error', "A short position can't be imported."],
      [3, 'error', 'Only TSX and US listings can be imported (RCI.B trades on NEOE).'],
      [4, 'error', 'The date is after today.'],
      [5, 'error', 'BONK is a coin, but the account is TFSA.'],
      [6, 'error', 'Can\'t read the quantity "lots".'],
      [7, 'ready', 'New position.'],
      [8, 'error', 'ABCD (TFSA) is in the report twice.'],
    ]) // no "not in the report" sells of the recorded VEEA or XRPN
  })
})
