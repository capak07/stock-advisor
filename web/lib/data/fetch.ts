import 'server-only'

/** PostgREST answers at most 1,000 rows per request (Supabase's default `max_rows`). */
const PAGE = 1000

type Answer<T> = { data: T | null; error: { message: string } | null }

/** Every row of a query, a page at a time. The query must have a stable order. */
export async function fetchAll<T>(page: (from: number, to: number) => PromiseLike<Answer<T[]>>): Promise<T[]> {
  const rows: T[] = []
  for (let from = 0; ; from += PAGE) {
    const { data, error } = await page(from, from + PAGE - 1)
    if (error) throw new Error(error.message)
    rows.push(...(data ?? []))
    if (!data || data.length < PAGE) return rows
  }
}

/** The data of an answer, or the error thrown. */
export const must = <T>({ data, error }: Answer<T>): T => {
  if (error) throw new Error(error.message)
  return data as T
}
