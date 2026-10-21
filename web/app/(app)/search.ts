'use server'

import { ownerClient } from '@/lib/auth'
import { loadSearchItems } from '@/lib/data/symbols'
import type { SearchItem } from '@/lib/symbol-search'

/** The stocks and coins the search boxes offer, asked for once per page load by the first search. */
export async function searchList(): Promise<SearchItem[]> {
  const supabase = await ownerClient()
  return supabase ? loadSearchItems(supabase) : []
}
