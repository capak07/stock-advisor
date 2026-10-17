/** Light or dark: the owner's choice on this device (localStorage), else the device setting. */

export type ThemeChoice = 'system' | 'light' | 'dark'
export const THEME_KEY = 'ledger-theme'

/** Runs in <head> before first paint, so a dark page never flashes light. */
export const THEME_SCRIPT = `(function(){var t=null;try{t=localStorage.getItem('${THEME_KEY}')}catch(e){}var d=t?t==='dark':matchMedia('(prefers-color-scheme: dark)').matches;document.documentElement.classList.toggle('dark',d)})()`

export function savedTheme(): ThemeChoice {
  try {
    const saved = localStorage.getItem(THEME_KEY)
    return saved === 'light' || saved === 'dark' ? saved : 'system'
  } catch {
    return 'system' // storage blocked
  }
}

export function applyTheme(choice: ThemeChoice): boolean {
  const dark = choice === 'dark' || (choice === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
  try {
    if (choice === 'system') localStorage.removeItem(THEME_KEY)
    else localStorage.setItem(THEME_KEY, choice)
  } catch {
    // storage blocked: the choice lasts until the page reloads
  }
  return dark
}
