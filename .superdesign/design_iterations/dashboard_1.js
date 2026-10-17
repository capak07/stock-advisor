/* Ledger dashboard mockups (superdesign step 4): Tailwind tokens, the app frame, light/dark, charts,
 * tabs, drawers, forms and the mockup-state switch. Loaded right after the Tailwind CDN script. */

// A script error lands on <html data-js-error>, so a headless render can show it.
window.addEventListener('error', (event) => { document.documentElement.dataset.jsError = event.message; });

tailwind.config = {
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        background: 'var(--background)', foreground: 'var(--foreground)', card: 'var(--card)',
        muted: 'var(--muted)', 'muted-foreground': 'var(--muted-foreground)', accent: 'var(--accent)',
        border: 'var(--border)', primary: 'var(--primary)', 'primary-foreground': 'var(--primary-foreground)',
        gain: 'var(--gain)', loss: 'var(--loss)', attention: 'var(--attention)', trim: 'var(--trim)', hold: 'var(--hold)',
        'gain-soft': 'var(--gain-soft)', 'loss-soft': 'var(--loss-soft)', 'attention-soft': 'var(--attention-soft)',
        'trim-soft': 'var(--trim-soft)', 'hold-soft': 'var(--hold-soft)',
      },
      fontFamily: {
        sans: ['Geist', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['Geist Mono', 'ui-monospace', 'monospace'],
      },
    },
  },
};

// Light or dark before first paint: the saved choice, else the device setting.
(function initTheme() {
  let saved = new URLSearchParams(window.location.search).get('theme');  // ?theme=dark for reviews
  try { saved = saved || localStorage.getItem('ledger-theme'); } catch { /* storage blocked */ }
  const dark = saved ? saved === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.classList.toggle('dark', dark);
})();

const Ledger = (() => {
  const NAV = [
    { href: 'portfolio_1.html', page: 'portfolio', label: 'Portfolio', icon: 'wallet' },
    { href: 'picks_1.html', page: 'picks', label: 'Picks', icon: 'sparkles' },
    { href: 'watchlist_1.html', page: 'watchlist', label: 'Watchlist', icon: 'eye' },
    { href: 'track_record_1.html', page: 'track', label: 'Track record', icon: 'chart-line' },
    { href: 'sources_1.html', page: 'sources', label: 'Sources', icon: 'activity' },
    { href: 'settings_1.html', page: 'settings', label: 'Settings', icon: 'settings' },
  ];
  const RUNS = [
    { when: 'Oct 16 · pre-close 15:31', dot: 'ok', status: 'success', sources: '30/33' },
    { when: 'Oct 16 · pre-open 08:24', dot: 'ok', status: 'success', sources: '31/33' },
    { when: 'Oct 15 · pre-close 15:29', dot: 'partial', status: 'degraded', sources: '29/33', note: 'Google News blocked' },
    { when: 'Oct 15 · pre-open 08:22', dot: 'ok', status: 'success', sources: '33/33' },
  ];
  const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const icon = (name, extra = '') => `<i data-lucide="${name}" ${extra}></i>`;
  const refreshIcons = () => window.lucide && window.lucide.createIcons();

  /* ---------- formatting ---------- */
  const fmtPct = (v, digits = 1) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}%`;
  const fmtMoney = (v, prefix = 'C$', digits = 0) =>
    `${v < 0 ? '−' : ''}${prefix}${Math.abs(v).toLocaleString('en-CA', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;

  /* ---------- app frame ---------- */
  function buildShell() {
    const page = document.body.dataset.page;
    const main = document.querySelector('main');
    if (!page || page === 'login' || !main) return;
    const navLinks = NAV.map((n) => `<a class="nav-link" href="${n.href}" ${n.page === page ? 'aria-current="page"' : ''}>${icon(n.icon)}${n.label}</a>`).join('');
    const runRows = RUNS.map((r) => `
      <div class="popover-row"><span class="dot ${r.dot}"></span>
        <span><span style="font-weight:500">${r.when}</span><br><span class="sub">${r.status}${r.note ? ` · ${r.note}` : ''}</span></span>
        <span class="num sub">${r.sources}</span></div>`).join('');
    const shell = document.createElement('div');
    shell.className = 'shell';
    shell.innerHTML = `
      <aside class="sidebar" aria-label="Main">
        <a class="brand" href="portfolio_1.html"><span class="brand-mark">A</span>ADVISOR</a>
        <nav style="display:grid;gap:2px">${navLinks}</nav>
        <label class="sidebar-search">${icon('search')}<input class="input" placeholder="Find ticker" aria-label="Find ticker" data-find-ticker></label>
        <div class="sidebar-foot"><span>Next run: pre-open Oct 19, 08:15</span><a href="login_1.html" class="muted">Sign out</a></div>
      </aside>
      <div class="content">
        <header class="statusbar">
          <a class="brand" href="portfolio_1.html"><span class="brand-mark">A</span></a>
          <button class="pill" data-popover="runs-pop" aria-haspopup="true"><span class="dot ok"></span>Pre-close 15:31<span class="muted hide-sm">success</span>${icon('chevron-down', 'style="width:14px;height:14px"')}</button>
          <a class="pill hide-sm" href="sources_1.html"><span class="num">30/33</span>&nbsp;sources</a>
          <span class="pill hide-sm" title="37 of 100 swing picks graded live"><span class="dot paper"></span>US Paper</span>
          <span class="pill hide-sm" title="12 of 100 swing picks graded live"><span class="dot paper"></span>TSX Paper</span>
          <span class="status-spacer"></span>
          <a class="icon-btn only-sm" href="ticker_1.html" aria-label="Find ticker">${icon('search')}</a>
          <button class="icon-btn" data-theme-toggle aria-label="Switch between light and dark">${icon(document.documentElement.classList.contains('dark') ? 'sun' : 'moon')}</button>
          <div class="popover" id="runs-pop" role="menu"><div class="label" style="padding:8px 10px 4px">Last runs</div>${runRows}</div>
        </header>
        <div class="banners" id="banners" aria-live="polite"></div>
        <footer class="disclaimer">Not financial or tax advice. Forecasts are probabilistic and can be wrong.</footer>
      </div>
      <nav class="bottom-tabs" aria-label="Main">
        ${NAV.slice(0, 3).map((n) => `<a class="bottom-tab" href="${n.href}" ${n.page === page ? 'aria-current="page"' : ''}>${icon(n.icon)}${n.label}</a>`).join('')}
        <button class="bottom-tab" data-open="more-sheet" ${['track', 'sources', 'settings', 'ticker'].includes(page) ? 'aria-current="page"' : ''}>${icon('ellipsis')}More</button>
      </nav>
      <div class="drawer" id="more-sheet" role="dialog" aria-modal="true" aria-label="More pages" aria-hidden="true">
        <div class="grab"></div>
        <div class="drawer-head"><h2>More</h2><button class="icon-btn" data-close aria-label="Close">${icon('x')}</button></div>
        <div class="drawer-body">${NAV.slice(3).map((n) => `<a class="nav-link" href="${n.href}">${icon(n.icon)}${n.label}</a>`).join('')}
          <a class="nav-link" href="ticker_1.html">${icon('search')}Find ticker</a></div>
      </div>`;
    const content = shell.querySelector('.content');
    content.insertBefore(main, content.querySelector('.disclaimer'));
    document.body.prepend(shell);
  }

  function addOverlays() {
    if (!document.querySelector('[data-backdrop]')) {
      const backdrop = document.createElement('div');
      backdrop.className = 'backdrop';
      backdrop.dataset.backdrop = '';
      document.body.append(backdrop);
    }
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.setAttribute('role', 'status');
    toast.innerHTML = `${icon('circle-check')}<span></span>`;
    document.body.append(toast);
  }

  /* ---------- theme ---------- */
  function initThemeToggle() {
    document.addEventListener('click', (event) => {
      const button = event.target.closest('[data-theme-toggle]');
      if (!button) return;
      const dark = !document.documentElement.classList.contains('dark');
      document.documentElement.classList.toggle('dark', dark);
      try { localStorage.setItem('ledger-theme', dark ? 'dark' : 'light'); } catch { /* storage blocked */ }
      button.innerHTML = icon(dark ? 'sun' : 'moon');
      refreshIcons();
    });
  }

  /* ---------- popovers ---------- */
  function initPopovers() {
    document.addEventListener('click', (event) => {
      const trigger = event.target.closest('[data-popover]');
      const open = document.querySelector('.popover.open');
      if (open && !event.target.closest('.popover') && (!trigger || trigger.dataset.popover !== open.id)) open.classList.remove('open');
      if (!trigger) return;
      const pop = document.getElementById(trigger.dataset.popover);
      const bar = trigger.offsetParent || document.body;
      pop.style.left = `${Math.min(trigger.offsetLeft, bar.clientWidth - 316)}px`;
      pop.style.top = `${trigger.offsetTop + trigger.offsetHeight + 6}px`;
      pop.classList.toggle('open');
    });
  }

  /* ---------- range bars ---------- */
  function initRanges(root = document) {
    root.querySelectorAll('.range[data-q10]').forEach((el) => {
      const q10 = +el.dataset.q10; const q50 = +el.dataset.q50; const q90 = +el.dataset.q90;
      const span = +(el.dataset.span || 12);
      const pos = (v) => Math.max(0, Math.min(100, 50 + (v / span) * 50));
      const left = pos(q10); const right = pos(q90); const mid = pos(q50);
      const origin = right > left ? ((mid - left) / (right - left)) * 100 : 50;
      el.innerHTML = `<div class="track"></div><div class="zero" style="left:50%"></div>
        <div class="band" style="left:${left}%;width:${right - left}%;--origin:${origin}%"></div><div class="mid" style="left:${mid}%"></div>`;
      const text = `Likely range q10 ${fmtPct(q10)}, median ${fmtPct(q50)}, q90 ${fmtPct(q90)}`;
      el.setAttribute('role', 'img');
      el.setAttribute('aria-label', text);
      el.title = text;
    });
  }

  /* ---------- tabs ---------- */
  function initTabs() {
    document.querySelectorAll('[data-tabs]').forEach((tabs) => {
      const group = tabs.dataset.tabs;
      const buttons = [...tabs.querySelectorAll('.tab')];
      const indicator = document.createElement('span');
      indicator.className = 'tab-indicator';
      tabs.prepend(indicator);
      tabs.setAttribute('role', 'tablist');
      const place = (button, animate) => {
        indicator.style.transition = animate ? '' : 'none';
        indicator.style.width = `${button.offsetWidth}px`;
        indicator.style.transform = `translateX(${button.offsetLeft - 3}px)`;
        indicator.style.left = '3px';
      };
      // Only a user's choice announces a change; the initial selection just draws the tab.
      const select = (button, animate = true, announce = true) => {
        buttons.forEach((b) => { b.setAttribute('aria-selected', String(b === button)); b.setAttribute('role', 'tab'); });
        place(button, animate);
        document.querySelectorAll(`[data-panel][data-group="${group}"]`).forEach((panel) => { panel.hidden = panel.dataset.panel !== button.dataset.tab; });
        if (announce) tabs.dispatchEvent(new CustomEvent('tabchange', { bubbles: true, detail: { group, value: button.dataset.tab } }));
      };
      buttons.forEach((b) => b.addEventListener('click', () => select(b)));
      const initial = buttons.find((b) => b.getAttribute('aria-selected') === 'true') || buttons[0];
      requestAnimationFrame(() => select(initial, false, false));
      window.addEventListener('resize', () => place(buttons.find((b) => b.getAttribute('aria-selected') === 'true') || initial, false));
      document.fonts && document.fonts.ready.then(() => place(buttons.find((b) => b.getAttribute('aria-selected') === 'true') || initial, false));
    });
  }

  /* ---------- drawers, forms, toasts ---------- */
  let lastFocus = null;
  function openDrawer(id) {
    const drawer = document.getElementById(id);
    if (!drawer) return;
    lastFocus = document.activeElement;
    document.querySelector('[data-backdrop]').classList.add('open');
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    setTimeout(() => (drawer.querySelector('input, select, a, button:not([data-close])') || drawer).focus(), reduceMotion() ? 0 : 260);
  }
  function closeDrawers() {
    document.querySelectorAll('.drawer.open').forEach((d) => { d.classList.remove('open'); d.setAttribute('aria-hidden', 'true'); });
    document.querySelector('[data-backdrop]')?.classList.remove('open');
    if (lastFocus) lastFocus.focus();
  }
  let toastTimer = null;
  function toast(message) {
    const el = document.querySelector('.toast');
    el.querySelector('span').textContent = message;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 4000);
  }
  function initDrawersAndForms() {
    document.addEventListener('click', (event) => {
      const opener = event.target.closest('[data-open]');
      if (opener) { event.preventDefault(); openDrawer(opener.dataset.open); return; }
      if (event.target.closest('[data-close]') || event.target.matches('[data-backdrop]')) closeDrawers();
    });
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') { closeDrawers(); document.querySelector('.popover.open')?.classList.remove('open'); } });
    document.querySelectorAll('form[data-mock-form]').forEach((form) => {
      form.addEventListener('input', (event) => event.target.closest('.field')?.classList.remove('invalid'));
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        let firstBad = null;
        form.querySelectorAll('[required]').forEach((input) => {
          const field = input.closest('.field');
          const bad = !String(input.value).trim();
          field.classList.toggle('invalid', bad);
          if (bad) {
            input.classList.remove('shake');
            void input.offsetWidth;
            input.classList.add('shake');
            firstBad = firstBad || input;
          }
        });
        if (firstBad) { firstBad.focus(); return; }
        const button = form.querySelector('[type="submit"]');
        const label = button.innerHTML;
        button.innerHTML = `${icon('check')}Saved`;
        refreshIcons();
        setTimeout(() => {
          closeDrawers();
          toast(form.dataset.toast || 'Saved');
          if (typeof window.onMockSave === 'function') window.onMockSave(form);
          button.innerHTML = label;
          refreshIcons();
          form.reset();
        }, 450);
      });
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && event.target.matches('[data-find-ticker]')) window.location.href = 'ticker_1.html';
    });
  }

  /* ---------- mockup states ---------- */
  const BANNERS = {
    stale: `
      <div class="banner danger">${icon('triangle-alert')}<div><strong>The 15:31 pre-close run failed:</strong> too few TSX prices loaded.
        Showing the 08:24 pre-open results until the next run.</div></div>
      <div class="banner warn">${icon('clock')}<div><strong>Missed slot:</strong> the Oct 19 pre-open run didn't start; GitHub's trigger arrived 52 minutes late.</div></div>`,
  };
  function initMockStates() {
    const states = document.body.dataset.states;
    if (!states) return;
    const options = states.split('|').map((pair) => pair.split(':'));
    const bar = document.createElement('div');
    bar.className = 'mock-switch';
    bar.innerHTML = `<span class="muted">Mockup only:</span>${options.map(([key, label]) => `<button data-state="${key}">${label}</button>`).join('')}`;
    document.body.append(bar);
    const pill = document.querySelector('[data-popover="runs-pop"]');
    const pillDefault = pill ? pill.innerHTML : '';
    const apply = (state) => {
      document.body.dataset.state = state;
      if (pill) {
        pill.innerHTML = state === 'stale'
          ? `<span class="dot failed"></span>Pre-close 15:31<span class="muted hide-sm">failed</span>${icon('chevron-down', 'style="width:14px;height:14px"')}`
          : pillDefault;
      }
      bar.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.state === state)));
      document.querySelectorAll('[data-show]').forEach((el) => { el.hidden = !el.dataset.show.split(' ').includes(state); });
      document.querySelectorAll('[data-hide]').forEach((el) => { el.hidden = el.dataset.hide.split(' ').includes(state); });
      const banners = document.getElementById('banners');
      if (banners) banners.innerHTML = BANNERS[state] || '';
      refreshIcons();
      document.dispatchEvent(new CustomEvent('statechange', { detail: state }));
    };
    bar.addEventListener('click', (event) => { const b = event.target.closest('button[data-state]'); if (b) apply(b.dataset.state); });
    const asked = new URLSearchParams(window.location.search).get('state');  // ?state=before for reviews
    apply(options.some(([key]) => key === asked) ? asked : options[0][0]);
  }

  /* ---------- charts ---------- */
  function rng(seed) {
    let a = seed >>> 0;
    return () => {
      a += 0x6d2b79f5;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  // A seeded random walk of n daily values that ends exactly at `end`.
  function walk({ seed, n, end, vol = 0.012, drift = 0.0003 }) {
    const random = rng(seed);
    const raw = [1];
    for (let i = 1; i < n; i += 1) {
      const shock = (random() + random() + random() - 1.5) * 2 * vol;
      raw.push(raw[i - 1] * Math.exp(drift + shock));
    }
    const scale = end / raw[n - 1];
    return raw.map((v) => v * scale);
  }
  // Labels for the n trading days ending on `last` (weekends skipped).
  function tradingDays(n, last = new Date(2026, 9, 16)) {
    const out = [];
    const d = new Date(last);
    while (out.length < n) {
      if (d.getDay() !== 0 && d.getDay() !== 6) out.unshift(d.toLocaleDateString('en-CA', { month: 'short', day: 'numeric' }));
      d.setDate(d.getDate() - 1);
    }
    return out;
  }
  function resample(values, k) {
    if (values.length === k) return values.slice();
    return Array.from({ length: k }, (_, i) => {
      const x = (i / (k - 1)) * (values.length - 1);
      const lo = Math.floor(x); const hi = Math.min(values.length - 1, lo + 1);
      return values[lo] + (values[hi] - values[lo]) * (x - lo);
    });
  }
  function tween(ms, step, done) {
    if (reduceMotion()) { step(1); if (done) done(); return; }
    const start = performance.now();
    const frame = (now) => {
      const k = Math.min(1, (now - start) / ms);
      step(k < 0.5 ? 2 * k * k : 1 - ((-2 * k + 2) ** 2) / 2);
      if (k < 1) requestAnimationFrame(frame); else if (done) done();
    };
    requestAnimationFrame(frame);
  }

  /**
   * A line chart with optional benchmark lines and a forecast cone.
   * opts: series, dates, benchmarks [{values, color, label}], cone {q10, q50, q90, label}, height, format(v), label.
   */
  function lineChart(el, opts) {
    // Drawn at the container's real width (1 unit = 1 px), so labels stay 10px on a phone; redrawn on resize.
    const H = opts.height || 240;
    const P = { l: 4, r: 62, t: 18, b: 26 };
    const plotH = H - P.t - P.b;
    let W = 800; let plotW = W - P.l - P.r;
    const measure = () => { W = Math.max(300, Math.round(el.clientWidth || 800)); plotW = W - P.l - P.r; };
    const format = opts.format || ((v) => v.toFixed(2));
    const state = { series: opts.series, benches: opts.benchmarks || [], cone: opts.cone || null, dates: opts.dates };
    el.classList.add('chart');
    el.innerHTML = `<svg role="img" aria-label="${opts.label || 'Chart'}"></svg><div class="tip"></div>`;
    const svg = el.querySelector('svg');
    const tip = el.querySelector('.tip');

    const geometry = () => {
      const histW = state.cone ? plotW * 0.76 : plotW;
      const last = state.series[state.series.length - 1];
      const values = [...state.series, ...state.benches.flatMap((b) => b.values)];
      if (state.cone) values.push(last * (1 + state.cone.q10 / 100), last * (1 + state.cone.q90 / 100));
      let lo = Math.min(...values); let hi = Math.max(...values);
      const pad = (hi - lo) * 0.1 || 1;
      lo -= pad; hi += pad;
      return {
        histW, last, lo, hi,
        x: (i, n) => P.l + (i / (n - 1)) * histW,
        y: (v) => P.t + (1 - (v - lo) / (hi - lo)) * plotH,
      };
    };
    const linePath = (values, g) => values.map((v, i) => `${i ? 'L' : 'M'}${g.x(i, values.length).toFixed(1)},${g.y(v).toFixed(1)}`).join('');

    function render(first) {
      measure();
      svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
      const g = geometry();
      const ticks = [0.15, 0.5, 0.85].map((f) => g.lo + (g.hi - g.lo) * (1 - f));
      const n = state.series.length;
      // With a cone, the cone's own labels use the right edge, so price ticks sit on the left above their lines.
      const tickText = (v) => (state.cone
        ? `<text x="${P.l + 2}" y="${g.y(v) - 5}">${format(v)}</text>`
        : `<text x="${W - 4}" y="${g.y(v) + 3}" text-anchor="end">${format(v)}</text>`);
      let html = `<g class="grid">${ticks.map((v) => `<line x1="${P.l}" x2="${state.cone ? W - 4 : P.l + plotW}" y1="${g.y(v)}" y2="${g.y(v)}"/>${tickText(v)}`).join('')}</g>`;
      state.benches.forEach((b) => {
        html += `<path d="${linePath(b.values, g)}" fill="none" stroke="${b.color}" stroke-width="1.6" stroke-linejoin="round" class="${first ? 'late' : ''}"/>`;
      });
      if (state.cone) {
        const x0 = P.l + g.histW; const x1 = P.l + plotW; const y0 = g.y(g.last);
        const at = (q) => g.y(g.last * (1 + q / 100));
        html += `<polygon points="${x0},${y0} ${x1},${at(state.cone.q90)} ${x1},${at(state.cone.q10)}" fill="var(--chart-5)" class="${first ? 'cone' : ''}" style="transform-origin:${x0}px ${y0}px"/>
          <path d="M${x0},${y0}L${x1},${at(state.cone.q50)}" stroke="var(--chart-4)" stroke-width="1.6" stroke-dasharray="5 4" class="${first ? 'cone' : ''}" style="transform-origin:${x0}px ${y0}px"/>
          <g class="${first ? 'late' : ''}">
            <text x="${x1 + 4}" y="${at(state.cone.q90) + 3}" style="fill:var(--gain)">${fmtPct(state.cone.q90)}</text>
            <text x="${x1 + 4}" y="${at(state.cone.q50) + 3}">${fmtPct(state.cone.q50)}</text>
            <text x="${x1 + 4}" y="${at(state.cone.q10) + 3}" style="fill:var(--loss)">${fmtPct(state.cone.q10)}</text>
            <text x="${x1}" y="${H - 6}" text-anchor="end">${(W < 560 ? state.cone.short : state.cone.label) || ''}</text>
          </g>`;
      }
      html += `<path d="${linePath(state.series, g)}" fill="none" stroke="var(--chart-1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" class="${first ? 'draw main-line' : 'main-line'}"/>
        <circle cx="${g.x(n - 1, n)}" cy="${g.y(g.last)}" r="4" fill="var(--chart-1)" stroke="var(--card)" stroke-width="2"/>
        <text x="${P.l}" y="${H - 6}">${state.dates[0]}</text>
        <text x="${g.x(n - 1, n)}" y="${H - 6}" text-anchor="${state.cone ? 'middle' : 'end'}">${state.cone ? 'today' : state.dates[n - 1]}</text>
        <line class="cross" x1="0" x2="0" y1="${P.t}" y2="${P.t + plotH}" stroke="var(--muted-foreground)" stroke-dasharray="3 3" opacity="0"/>
        <circle class="cross-dot" r="4" fill="var(--chart-1)" opacity="0"/>`;
      svg.innerHTML = html;
      if (first) {
        const line = svg.querySelector('.main-line');
        line.style.setProperty('--len', String(Math.ceil(line.getTotalLength())));
      }
      state.g = g;
    }

    svg.addEventListener('pointermove', (event) => {
      const g = state.g; const n = state.series.length;
      const box = svg.getBoundingClientRect();
      const sx = ((event.clientX - box.left) / box.width) * W;
      const i = Math.round(((sx - P.l) / g.histW) * (n - 1));
      if (i < 0 || i >= n) { tip.classList.remove('show'); return; }
      const cx = g.x(i, n); const cy = g.y(state.series[i]);
      const cross = svg.querySelector('.cross'); const dot = svg.querySelector('.cross-dot');
      cross.setAttribute('x1', cx); cross.setAttribute('x2', cx); cross.setAttribute('opacity', '0.6');
      dot.setAttribute('cx', cx); dot.setAttribute('cy', cy); dot.setAttribute('opacity', '1');
      tip.innerHTML = `<span class="muted">${state.dates[i] || ''}</span> <span class="num" style="font-weight:600">${format(state.series[i])}</span>`;
      tip.style.left = `${Math.min(box.width - 150, Math.max(0, (cx / W) * box.width - 60))}px`;
      tip.style.top = `${Math.max(0, (cy / H) * box.height - 44)}px`;
      tip.classList.add('show');
    });
    svg.addEventListener('pointerleave', () => {
      tip.classList.remove('show');
      svg.querySelector('.cross')?.setAttribute('opacity', '0');
      svg.querySelector('.cross-dot')?.setAttribute('opacity', '0');
    });

    render(true);
    let queued = false;
    new ResizeObserver(() => {
      if (queued || Math.max(300, Math.round(el.clientWidth || 800)) === W) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; render(false); });
    }).observe(el);
    return {
      // Morph the cone to another horizon's quantiles (300 ms).
      setCone(cone) {
        const from = { ...state.cone };
        tween(300, (k) => {
          state.cone = { label: cone.label, short: cone.short, q10: from.q10 + (cone.q10 - from.q10) * k, q50: from.q50 + (cone.q50 - from.q50) * k, q90: from.q90 + (cone.q90 - from.q90) * k };
          render(false);
        });
      },
      // Morph to another window of the same data (250 ms): both are resampled to the same length.
      setSeries(series, benches, dates) {
        const K = 160;
        const fromS = resample(state.series, K); const toS = resample(series, K);
        const fromB = state.benches.map((b) => resample(b.values, K)); const toB = benches.map((b) => resample(b.values, K));
        state.dates = resample(dates.map((_, i) => i), K).map((x) => dates[Math.round(x)]);
        tween(250, (k) => {
          state.series = fromS.map((v, i) => v + (toS[i] - v) * k);
          state.benches = benches.map((b, j) => ({ ...b, values: (fromB[j] || toB[j]).map((v, i) => v + (toB[j][i] - v) * k) }));
          render(false);
        });
      },
    };
  }

  /* ---------- number tween (period toggle) ---------- */
  function tweenNumber(el, to, format) {
    const from = parseFloat(el.dataset.value || '0');
    el.dataset.value = String(to);
    tween(250, (k) => { el.textContent = format(from + (to - from) * k); });
  }

  function stagger() {
    document.querySelectorAll('.stagger').forEach((list) => [...list.children].forEach((child, i) => child.style.setProperty('--i', String(i))));
  }

  document.addEventListener('DOMContentLoaded', () => {
    buildShell();
    addOverlays();
    initThemeToggle();
    initPopovers();
    initRanges();
    initTabs();
    initDrawersAndForms();
    stagger();
    if (typeof window.initPage === 'function') window.initPage();
    initMockStates();
    refreshIcons();
  });

  return { walk, tradingDays, lineChart, tweenNumber, initRanges, toast, fmtPct, fmtMoney, refreshIcons, resample };
})();
