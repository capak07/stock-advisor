'use server'

import { unstable_cache } from 'next/cache'
import { ownerClient } from '@/lib/auth'
import { listsStamp, loadSearchItems } from '@/lib/data/symbols'
import { toRows, type SearchRow } from '@/lib/symbol-search'

/**
 * The stocks and coins the search boxes offer, as compact rows, asked for once per page load by
 * the first search. Reading thousands of stocks takes several pages, so the rows are cached on
 * the server under a stamp of the lists, which changes whenever a run adds, renames or drops one.
 */
export async function searchList(): Promise<SearchRow[]> {
  const supabase = await ownerClient()
  if (!supabase) throw new Error('Only the owner can search the lists.')
  const stamp = await listsStamp(supabase)
  return unstable_cache(async () => toRows(await loadSearchItems(supabase)), ['search-list', stamp])()
}
