import { expect, test as setup } from '@playwright/test'
import { createClient } from '@supabase/supabase-js'
import { sql } from './db'
import { OWNER, OWNER_STATE, VISITOR, localStack } from './stack'

/** Creates the owner and a second user on the local stack, names the owner, and signs in once. */
setup('owner and visitor exist, and the owner is signed in', async ({ page }) => {
  const stack = localStack()
  const admin = createClient(stack.API_URL, stack.SECRET_KEY, { auth: { persistSession: false } })
  const { data: list, error } = await admin.auth.admin.listUsers()
  if (error) throw error
  const ids: Record<string, string> = {}
  for (const account of [OWNER, VISITOR]) {
    const existing = list.users.find((u) => u.email === account.email)
    if (existing) {
      await admin.auth.admin.updateUserById(existing.id, { password: account.password })
      ids[account.email] = existing.id
    } else {
      const { data, error: createError } = await admin.auth.admin.createUser({ ...account, email_confirm: true })
      if (createError) throw createError
      ids[account.email] = data.user.id
    }
  }
  await sql`insert into app_config (id, owner_id) values (1, ${ids[OWNER.email]})
            on conflict (id) do update set owner_id = excluded.owner_id`

  await page.goto('/login')
  await page.getByLabel('Email').fill(OWNER.email)
  await page.getByLabel('Password').fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'My Portfolio' })).toBeVisible()
  await page.context().storageState({ path: OWNER_STATE })
})
