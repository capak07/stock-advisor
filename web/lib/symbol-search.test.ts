import { describe, expect, it } from 'vitest'
import { displayName, highlight, searchSymbols, type SearchItem } from './symbol-search'

const stock = (symbol: string, name: string): SearchItem => ({
  symbol,
  name,
  assetType: 'stock',
  kind: symbol.endsWith('.TO') ? 'TSX' : 'US',
})
const coin = (symbol: string, name: string): SearchItem => ({ symbol, name, assetType: 'crypto', kind: 'Crypto' })

const ITEMS: SearchItem[] = [
  stock('RY', 'Royal Bank Of Canada Common Stock'),
  stock('RY.TO', 'Royal Bank of Canada'),
  stock('RGLD', 'Royal Gold, Inc. - Common Stock'),
  stock('RCL', 'Royal Caribbean Cruises Ltd. Common Stock'),
  stock('SHOP', 'Shopify Inc. Class A Subordinate Voting Shares'),
  stock('SHOP.TO', 'Shopify Inc.'),
  stock('LOYL', 'Loyalty Ventures Inc. Common Stock'),
  stock('BRK.B', 'Berkshire Hathaway Inc. New Common Stock'),
  coin('ETH', 'Ethereum'),
  coin('ETC', 'Ethereum Classic'),
  coin('SHIB', 'Shiba Inu'),
]

const symbols = (query: string, max?: number) => searchSymbols(ITEMS, query, max).map((i) => i.symbol)

describe('symbol search', () => {
  it('finds companies by a word of their name: TSX, then US, then coins, then list order', () => {
    expect(symbols('royal')).toEqual(['RY.TO', 'RY', 'RGLD', 'RCL'])
    expect(symbols('oyal')).toEqual(['RY.TO', 'RY', 'RGLD', 'RCL', 'LOYL'])
  })

  it('puts an exact ticker first, then tickers that start with the query', () => {
    expect(symbols('ry')).toEqual(['RY.TO', 'RY'])
    expect(symbols('shop')).toEqual(['SHOP.TO', 'SHOP'])
    expect(symbols('sh')).toEqual(['SHOP.TO', 'SHOP', 'SHIB', 'BRK.B']) // Berk*sh*ire, inside a word, comes last
  })

  it('matches share classes and TSX tickers in any form people type', () => {
    expect(symbols('brk.b')).toEqual(['BRK.B'])
    expect(symbols('ry.to')).toEqual(['RY.TO'])
  })

  it('finds coins by name or ticker', () => {
    expect(symbols('ether')).toEqual(['ETH', 'ETC'])
    expect(symbols('eth')).toEqual(['ETH', 'ETC'])
  })

  it('returns nothing for an empty query and at most the asked number', () => {
    expect(symbols('   ')).toEqual([])
    expect(symbols('o', 3)).toHaveLength(3)
  })

  it('shows directory names without the share description', () => {
    expect(displayName('Royal Gold, Inc. - Common Stock')).toBe('Royal Gold, Inc.')
    expect(displayName('Royal Caribbean Cruises Ltd. Common Stock')).toBe('Royal Caribbean Cruises Ltd.')
    expect(displayName('Shopify Inc. Class A Subordinate Voting Shares')).toBe('Shopify Inc.')
    expect(displayName('Berkshire Hathaway Inc. New Common Stock')).toBe('Berkshire Hathaway Inc.')
    expect(displayName('Taiwan Semiconductor Manufacturing Company Ltd. American Depositary Shares (each representing 5)')).toBe(
      'Taiwan Semiconductor Manufacturing Company Ltd.',
    )
    expect(displayName('Ethereum')).toBe('Ethereum')
  })

  it('marks the part of the name that matched', () => {
    expect(highlight('Royal Bank of Canada', 'royal')).toEqual([
      { text: 'Royal', match: true },
      { text: ' Bank of Canada', match: false },
    ])
    expect(highlight('Loyalty Ventures', 'oyal')).toEqual([
      { text: 'L', match: false },
      { text: 'oyal', match: true },
      { text: 'ty Ventures', match: false },
    ])
    expect(highlight('Apple', 'zz')).toEqual([{ text: 'Apple', match: false }])
  })
})
