/* Glass UI behaviour for the mockups: theme, aurora pause, sliding pills, rim light, tab bar hide, stagger, line draw,
 * search popover and sheets. The app gets the same effects from its own components; this file only makes the mockups feel real. */
(() => {
  const $ = (s, r = document) => r.querySelector(s)
  const $$ = (s, r = document) => [...r.querySelectorAll(s)]
  const root = document.documentElement

  // Theme: ?theme=dark for screenshots, otherwise the device setting; the moon button flips it.
  const q = new URLSearchParams(location.search).get('theme')
  if (q === 'dark' || (!q && matchMedia('(prefers-color-scheme: dark)').matches)) root.classList.add('dark')
  $$('[data-theme-toggle]').forEach((b) => b.addEventListener('click', () => root.classList.toggle('dark')))

  // The aurora rests while the page is hidden.
  const aurora = $('.aurora')
  document.addEventListener('visibilitychange', () => aurora && aurora.classList.toggle('paused', document.hidden))

  // Cards enter in order (first six staggered).
  $$('.enter').forEach((el, i) => el.style.setProperty('--i', Math.min(i, 6)))

  // Sidebar pill sits under the current link and slides to a clicked one.
  const nav = $('.nav')
  if (nav) {
    const pill = document.createElement('span'); pill.className = 'nav-pill'; nav.prepend(pill)
    const place = (a) => { pill.style.transform = `translateY(${a.offsetTop}px)` }
    const cur = $('.nav-link[aria-current="page"]', nav); if (cur) place(cur); else pill.style.opacity = 0
    $$('.nav-link', nav).forEach((a) => a.addEventListener('click', (e) => {
      e.preventDefault(); $$('.nav-link', nav).forEach((x) => x.removeAttribute('aria-current'))
      a.setAttribute('aria-current', 'page'); pill.style.opacity = 1; place(a)
    }))
  }

  // Tab bar: the liquid pill slides and stretches to the tapped tab; the bar hides while scrolling down.
  const bar = $('.tabbar')
  if (bar) {
    const pill = document.createElement('span'); pill.className = 'tab-pill'; bar.prepend(pill)
    const tabs = $$('.tab', bar)
    const place = (t) => { pill.style.width = `${t.offsetWidth}px`; pill.style.transform = `translateX(${t.offsetLeft - 6}px)` }
    // Pages under More have no current tab: the pill stays hidden until a tab is tapped.
    const current = () => tabs.find((t) => t.getAttribute('aria-current') === 'page')
    const cur = current()
    if (cur) requestAnimationFrame(() => place(cur)); else pill.style.opacity = 0
    addEventListener('resize', () => { const c = current(); if (c) place(c) })
    tabs.forEach((t) => t.addEventListener('click', (e) => {
      if (t.dataset.sheet) return // More opens its sheet; the pill stays put
      e.preventDefault(); tabs.forEach((x) => x.removeAttribute('aria-current')); t.setAttribute('aria-current', 'page')
      pill.style.opacity = 1; pill.classList.remove('stretch'); void pill.offsetWidth; pill.classList.add('stretch'); place(t)
    }))
    let last = scrollY
    addEventListener('scroll', () => {
      const y = scrollY; if (Math.abs(y - last) < 6) return
      bar.classList.toggle('hidden', y > last && y > 120); last = y
    }, { passive: true })
  }

  // Rim light follows the pointer across glass cards (desktop pointers only).
  if (matchMedia('(hover: hover)').matches) {
    $$('.card.rim').forEach((c) => c.addEventListener('pointermove', (e) => {
      const r = c.getBoundingClientRect()
      c.style.setProperty('--mx', `${e.clientX - r.left}px`); c.style.setProperty('--my', `${e.clientY - r.top}px`)
    }))
  }

  // Chart lines draw once.
  $$('.draw path.line').forEach((p) => p.style.setProperty('--len', Math.ceil(p.getTotalLength())))

  // Search: results open under the bar on focus.
  $$('[data-search]').forEach((box) => {
    const input = $('input', box), pop = $('.popover', box)
    if (!input || !pop) return
    input.addEventListener('focus', () => pop.classList.add('open'))
    input.addEventListener('blur', () => setTimeout(() => pop.classList.remove('open'), 120))
  })

  // Sheets: [data-sheet="id"] opens #id with the scrim; the scrim or [data-close] shuts it.
  const scrim = $('.scrim')
  const close = () => { $$('.sheet.open').forEach((s) => s.classList.remove('open')); scrim && scrim.classList.remove('open') }
  $$('[data-sheet]').forEach((b) => b.addEventListener('click', (e) => {
    e.preventDefault(); const s = document.getElementById(b.dataset.sheet); if (!s) return
    s.classList.add('open'); scrim && scrim.classList.add('open')
  }))
  scrim && scrim.addEventListener('click', close)
  $$('[data-close]').forEach((b) => b.addEventListener('click', close))

  // Price ticks: [data-tick] buttons flash the prices once, up or down.
  $$('[data-tick]').forEach((b) => b.addEventListener('click', () => $$('[data-price]').forEach((el) => {
    const cls = el.dataset.price === 'down' ? 'tick-down' : 'tick-up'; el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls)
  })))

  if (window.lucide) lucide.createIcons()
})()
