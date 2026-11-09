/** 8-K item numbers in plain words. Labels from github.com/Jakeschincariol/day-trader-skill (MIT). */
export const ITEM_LABELS: Record<string, string> = {
  '1.01': 'material agreement', '1.02': 'agreement ended', '1.03': 'bankruptcy',
  '1.05': 'cybersecurity incident', '2.01': 'acquisition or sale of assets',
  '2.02': 'earnings results', '2.03': 'new debt', '2.04': 'debt acceleration',
  '2.05': 'restructuring costs', '2.06': 'impairment', '3.01': 'delisting notice',
  '3.02': 'unregistered share sale', '3.03': 'shareholder rights change',
  '4.01': 'auditor change', '4.02': 'past financials no longer reliable',
  '5.01': 'change in control', '5.02': 'director or officer change',
  '5.03': 'bylaws or fiscal year change', '5.07': 'shareholder vote results',
  '7.01': 'Regulation FD disclosure', '8.01': 'other events', '9.01': 'exhibits',
}

/** Items worth flagging (same set as the skill). */
export const IMPORTANT_ITEMS: ReadonlySet<string> = new Set([
  '1.03', '1.05', '2.02', '2.04', '2.06', '3.01', '4.02', '5.01', '5.02',
])

/** Labels for a filing's items; the exhibits item (9.01) says nothing, so it is dropped. */
export const itemLabels = (items: string[]): string[] =>
  items.filter((item) => item !== '9.01').map((item) => ITEM_LABELS[item] ?? `item ${item}`)

export const isImportant = (items: string[]): boolean => items.some((item) => IMPORTANT_ITEMS.has(item))
