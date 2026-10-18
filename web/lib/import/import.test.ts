import { describe, expect, it } from 'vitest'
import type { Trade } from '../portfolio/types'
import { parseCsv } from './csv'
import { guessMeanings, meaningProblems, readAccount, readDate, readRows, readSide, type Meaning } from './rows'

describe('parseCsv', () => {
  it('reads quoted fields with commas, doubled quotes and line breaks', () => {
    const text = '﻿date,description,amount\r\n2026-10-03,"Bought 10 RY, ""at market""",-1840.00\r\n"2026-10-04","two\nlines",5\r\n\r\n'
    expect(parseCsv(text)).toEqual([
      ['date', 'description', 'amount'],
      ['2026-10-03', 'Bought 10 RY, "at market"', '-1840.00'],
      ['2026-10-04', 'two\nlines', '5'],
    ])
  })

  it('uses the delimiter the header uses', () => {
    expect(parseCsv('date;symbol\n2026-10-03;RY')).toEqual([['date', 'symbol'], ['2026-10-03', 'RY']])
    expect(parseCsv('date\tsymbol\n2026-10-03\tRY')).toEqual([['date', 'symbol'], ['2026-10-03', 'RY']])
  })
})

describe('column meanings', () => {
  it('guesses from the headers, each meaning once', () => {
    expect(
      guessMeanings(['Date', 'Activity Type', 'Symbol', 'Quantity', 'Price', 'Account', 'Currency', 'Net Amount', 'Date']),
    ).toEqual(['date', 'side', 'symbol', 'quantity', 'price', 'account', 'currency', 'ignore', 'ignore'])
  })

  it('names what is missing or chosen twice', () => {
    const meanings: Meaning[] = ['date', 'date', 'symbol', 'quantity', 'price']
    expect(meaningProblems(meanings, true)).toEqual([
      'Date is chosen for 2 columns.',
      'Choose the column with the buy or sell.',
      'Choose the column with the account.',
    ])
    expect(meaningProblems(['date', 'side', 'symbol', 'quantity', 'price'], false)).toEqual([])
  })
})

describe('reading values', () => {
  it('reads ISO, written-out and slashed dates, and refuses impossible ones', () => {
    expect(readDate('2026-10-03', 'ymd')).toBe('2026-10-03')
    expect(readDate('2026-10-03 09:31:00', 'mdy')).toBe('2026-10-03')
    expect(readDate('Oct 3, 2026', 'ymd')).toBe('2026-10-03')
    expect(readDate('3 October 2026', 'ymd')).toBe('2026-10-03')
    expect(readDate('10/03/2026', 'mdy')).toBe('2026-10-03')
    expect(readDate('03/10/2026', 'dmy')).toBe('2026-10-03')
    expect(readDate('2026-02-30', 'ymd')).toBeNull()
    expect(readDate('yesterday', 'ymd')).toBeNull()
  })

  it("reads sides and accounts in brokers' words", () => {
    expect([readSide('BUY'), readSide('Market sell'), readSide('Dividend'), readSide('purchase')]).toEqual([
      'buy', 'sell', null, 'buy',
    ])
    expect([readAccount('TFSA - Self-directed'), readAccount('Crypto'), readAccount('Personal'), readAccount('Chequing')]).toEqual([
      'tfsa', 'crypto', 'non_registered', null,
    ])
  })
})

describe('readRows', () => {
  const header = ['date', 'type', 'symbol', 'quantity', 'price', 'currency', 'account']
  const meanings: Meaning[] = ['date', 'side', 'symbol', 'quantity', 'price', 'currency', 'account']
  const options = { meanings, account: null, dateOrder: 'ymd' as const, today: '2026-10-16', existing: [] as Trade[] }

  it('reads buys and sells, a bare CAD symbol as TSX, and coins in the crypto account', () => {
    const rows = readRows(
      [
        header,
        ['2026-10-03', 'Buy', 'RY', '10', 'C$184.50', 'CAD', 'TFSA'],
        ['2026-10-04', 'Sell', 'aapl', '-2', '$230', 'USD', 'TFSA'],
        ['2026-10-05', 'Buy', 'BTC', '0.015', '98,000', 'CAD', 'Crypto'],
      ],
      options,
    )
    expect(rows.map((r) => [r.line, r.status, r.trade?.symbol, r.trade?.side, r.trade?.qty, r.trade?.price])).toEqual([
      [2, 'ready', 'RY.TO', 'buy', 10, 184.5],
      [3, 'ready', 'AAPL', 'sell', 2, 230],
      [4, 'ready', 'BTC', 'buy', 0.015, 98000],
    ])
    expect(rows[2].trade?.assetType).toBe('crypto')
  })

  it('keeps a TSX symbol already written with .TO, and a dotted class as it is', () => {
    const rows = readRows(
      [
        header,
        ['2026-10-03', 'Buy', 'RY.TO', '10', '184.50', 'CAD', 'TFSA'],
        ['2026-10-04', 'Buy', 'RCI.B.TO', '5', '60', 'CAD', 'TFSA'],
      ],
      options,
    )
    expect(rows.map((r) => [r.status, r.trade?.symbol])).toEqual([
      ['ready', 'RY.TO'],
      ['ready', 'RCI-B.TO'],
    ])
  })

  it('leaves out what is not a trade, and says why each bad row is wrong', () => {
    const rows = readRows(
      [
        header,
        ['2026-10-03', 'Dividend', 'RY', '', '', 'CAD', 'TFSA'],
        ['2026-13-01', 'Buy', 'RY', '1', '1', 'CAD', 'TFSA'],
        ['2026-10-03', 'Buy', 'RY', '1', '1', 'CAD', 'Chequing'],
        ['2026-10-17', 'Buy', 'RY', '1', '1', 'CAD', 'TFSA'],
        ['2026-10-03', 'Buy', 'NOT A SYMBOL', '1', '1', 'USD', 'TFSA'],
        ['2026-10-03', 'Buy', 'RY', 'ten', '1', 'CAD', 'TFSA'],
      ],
      options,
    )
    expect(rows.map((r) => [r.status, r.reason])).toEqual([
      ['skipped', 'Not a buy or a sell (Dividend).'],
      ['error', 'Can\'t read the date "2026-13-01".'],
      ['error', 'Unknown account "Chequing".'],
      ['error', 'The date is after today.'],
      ['error', '"NOT A SYMBOL" isn\'t a stock symbol.'],
      ['error', 'Can\'t read the quantity "ten".'],
    ])
  })

  it('marks a trade already recorded, or twice in the file, as a duplicate', () => {
    const existing: Trade[] = [{
      side: 'buy', account: 'tfsa', symbol: 'RY.TO', assetType: 'stock', qty: 10, price: 184.5,
      currency: 'CAD', fxRateCad: null, day: '2026-10-03',
    }]
    const rows = readRows(
      [
        header,
        ['2026-10-03', 'Buy', 'RY', '10', '184.50', 'CAD', 'TFSA'],
        ['2026-10-04', 'Buy', 'TD', '5', '80', 'CAD', 'TFSA'],
        ['2026-10-04', 'Buy', 'TD', '5', '80', 'CAD', 'TFSA'],
      ],
      { ...options, existing },
    )
    expect(rows.map((r) => [r.status, r.reason])).toEqual([
      ['duplicate', 'Already recorded.'],
      ['ready', null],
      ['duplicate', 'Twice in this file.'],
    ])
  })

  it('uses one account for the whole file when there is no account column', () => {
    const rows = readRows(
      [['date', 'type', 'symbol', 'quantity', 'price'], ['2026-10-03', 'Buy', 'ETH', '1', '4000']],
      { ...options, meanings: ['date', 'side', 'symbol', 'quantity', 'price'], account: 'crypto' },
    )
    expect(rows[0].trade).toMatchObject({ account: 'crypto', assetType: 'crypto', symbol: 'ETH' })
  })

  it("keeps a US stock's rate from the file, and refuses one that isn't a rate", () => {
    const withRate = [...header, 'fx']
    const m: Meaning[] = [...meanings, 'fxRate']
    const rows = readRows(
      [withRate, ['2026-10-03', 'Buy', 'AAPL', '1', '230', 'USD', 'TFSA', '1.3918'], ['2026-10-03', 'Buy', 'MSFT', '1', '410', 'USD', 'TFSA', '139']],
      { ...options, meanings: m },
    )
    expect(rows[0].trade?.fxRate).toBe(1.3918)
    expect(rows[1]).toMatchObject({ status: 'error', reason: 'Can\'t read the USD/CAD rate "139".' })
  })
})
