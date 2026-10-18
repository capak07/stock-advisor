/** A small CSV reader for broker activity files (spec §7.1, file import). */

const DELIMITERS = [',', ';', '\t'] as const

/** The delimiter the header line uses most: comma, semicolon or tab. */
function delimiterOf(text: string): string {
  const header = text.split(/\r?\n/, 1)[0] ?? ''
  let best: string = ','
  let most = -1
  for (const d of DELIMITERS) {
    const count = header.split(d).length - 1
    if (count > most) {
      best = d
      most = count
    }
  }
  return best
}

/**
 * Rows of fields. Quoted fields may hold the delimiter, line breaks and doubled quotes (`""`).
 * A byte-order mark, CRLF line ends and blank lines are tolerated.
 */
export function parseCsv(input: string): string[][] {
  const text = input.replace(/^﻿/, '')
  const delimiter = delimiterOf(text)
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i]
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"'
        i += 1
      } else if (c === '"') {
        quoted = false
      } else {
        field += c
      }
    } else if (c === '"' && field === '') {
      quoted = true
    } else if (c === delimiter) {
      row.push(field)
      field = ''
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i += 1
      row.push(field)
      if (row.some((f) => f.trim() !== '')) rows.push(row)
      row = []
      field = ''
    } else {
      field += c
    }
  }
  row.push(field)
  if (row.some((f) => f.trim() !== '')) rows.push(row)
  return rows.map((r) => r.map((f) => f.trim()))
}
