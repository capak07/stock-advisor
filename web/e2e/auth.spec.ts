import { expect, test } from '@playwright/test'
import { resetData } from './db'
import { OWNER, VISITOR, localStack } from './stack'

test.use({ storageState: { cookies: [], origins: [] } })
test.beforeEach(resetData)

test('a signed-out visitor is sent to the sign-in page', async ({ page }) => {
  await page.goto('/watchlist')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByText('Not financial or tax advice. Forecasts are probabilistic and can be wrong.')).toBeVisible()
})

test('a wrong password is refused, and the email stays filled in', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill(OWNER.email)
  await page.getByLabel('Password').fill('not-the-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText("That email and password don't match.")).toBeVisible()
  await expect(page.getByLabel('Email')).toHaveValue(OWNER.email)
})

test('empty fields are named', async ({ page }) => {
  await page.goto('/login')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText('Enter your email.')).toBeVisible()
  await expect(page.getByText('Enter your password.')).toBeVisible()
})

test('the owner signs in and out', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill(OWNER.email)
  await page.getByLabel('Password').fill(OWNER.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'My Portfolio' })).toBeVisible()

  await page.goto('/login')
  await expect(page).toHaveURL(/\/$/) // a signed-in owner doesn't see the sign-in page

  await page.getByRole('complementary', { name: 'Main' }).getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
})

test('nobody can sign up', async ({ request }) => {
  const stack = localStack()
  const response = await request.post(`${stack.API_URL}/auth/v1/signup`, {
    headers: { apikey: stack.PUBLISHABLE_KEY },
    data: { email: 'stranger@example.com', password: 'stranger-password-1' },
  })
  expect(response.status()).toBe(422)
  expect((await response.json()).error_code).toBe('signup_disabled')
})

test('someone who is not the owner sees no data', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill(VISITOR.email)
  await page.getByLabel('Password').fill(VISITOR.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText("This account isn't the owner")).toBeVisible()
  await expect(page.getByRole('heading', { name: 'My Portfolio' })).toHaveCount(0)
})
