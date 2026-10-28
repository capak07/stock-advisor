import 'server-only'
import { cookies } from 'next/headers'
import { QUOTES_COOKIE, decodeQuotes, type LiveQuotes } from '../quotes'

/** The live quotes the owner last refreshed, or null when none are under an hour old. */
export async function liveQuotes(): Promise<LiveQuotes | null> {
  return decodeQuotes((await cookies()).get(QUOTES_COOKIE)?.value, new Date())
}
