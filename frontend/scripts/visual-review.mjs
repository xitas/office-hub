/**
 * Visual review: screenshots every Phase 1 page for each role, theme, language and viewport,
 * and flags layout problems automatically (horizontal overflow, off-screen popups, clipped text,
 * wrong text direction, console errors).
 *
 * Prereqs: backend on :8000 with `seed_demo` data (set LOGIN_THROTTLE_RATE=1000/min for the run),
 * Vite on :5173, and Google Chrome installed.
 *
 *   node scripts/visual-review.mjs                 # everything
 *   node scripts/visual-review.mjs --only=admin    # one role (admin|manager|staff|public)
 *
 * Output: ../review-screenshots/<viewport>/<theme>-<lang>/<role>-<page>.png and report.json
 */
import { createHmac } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const BASE = process.env.REVIEW_URL ?? 'http://localhost:5173'
const API = `${BASE}/api/v1`
const PASSWORD = 'Demo@12345'
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../review-screenshots')
const ONLY = process.argv.find((a) => a.startsWith('--only='))?.split('=')[1]

const VIEWPORTS = {
  desktop: { viewport: { width: 1440, height: 900 } },
  phone: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
}
const THEMES = ['light', 'dark']
const LANGS = ['en', 'ur']
const ROLES = {
  admin: 'admin@office.test',
  manager: 'sales.manager@office.test',
  staff: 'hamza@office.test',
}
const TWO_FA_USER = 'zainab@office.test'

const report = { generatedAt: new Date().toISOString(), shots: 0, issues: [], consoleErrors: [] }

// ---------------------------------------------------------------- API helpers
async function apiLogin(email) {
  const res = await fetch(`${API}/auth/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password: PASSWORD, client: 'mobile' }),
  })
  if (!res.ok) throw new Error(`login ${email}: ${res.status} ${await res.text()}`)
  return (await res.json()).access
}
const call = (token, method, url, body) =>
  fetch(`${API}${url}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })

function totp(base32) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  let bits = ''
  for (const c of base32.replace(/=+$/, '')) bits += alphabet.indexOf(c).toString(2).padStart(5, '0')
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)))
  const counter = Buffer.alloc(8)
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)))
  const h = createHmac('sha1', key).update(counter).digest()
  const o = h[h.length - 1] & 0xf
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1e6).padStart(6, '0')
}

/** Realistic content: notifications for manager and staff, activity entries, one 2FA user. */
async function prepareData() {
  const admin = await apiLogin(ROLES.admin)
  const users = (await (await call(admin, 'GET', '/users/?page_size=100')).json()).results
  const depts = (await (await call(admin, 'GET', '/departments/?page_size=100')).json()).results
  const byEmail = Object.fromEntries(users.map((u) => [u.email, u]))
  const dept = Object.fromEntries(depts.map((d) => [d.name, d]))

  const staff = byEmail[ROLES.staff]
  await call(admin, 'PATCH', `/users/${staff.id}/`, { role: 'manager' })
  await call(admin, 'PATCH', `/users/${staff.id}/`, { role: 'staff', job_title: 'Senior Sales Executive' })
  const mgr = byEmail[ROLES.manager]
  await call(admin, 'PATCH', `/users/${mgr.id}/`, { department: dept.Operations.id })
  await call(admin, 'PATCH', `/users/${mgr.id}/`, { department: dept.Sales.id })
  await call(admin, 'PATCH', `/users/${byEmail['fatima@office.test'].id}/`, { phone: '0300 1234567' })

  // A 2FA-enabled account for the OTP screen.
  const z = await apiLogin(TWO_FA_USER).catch(() => null)
  if (z) {
    await call(z, 'POST', '/auth/2fa/disable/', { password: PASSWORD })
    const { secret } = await (await call(z, 'POST', '/auth/2fa/setup/')).json()
    await call(z, 'POST', '/auth/2fa/enable/', { code: totp(secret) })
  }
  return { users: byEmail, depts: dept }
}

// ---------------------------------------------------------------- page checks
async function inspect(page) {
  return page.evaluate(() => {
    const vw = window.innerWidth
    const vh = window.innerHeight
    const problems = []
    const describe = (el) => {
      const text = (el.innerText || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 60)
      return `${el.tagName.toLowerCase()}${el.dataset.slot ? `[${el.dataset.slot}]` : ''} "${text}"`
    }
    const inScroller = (el) => {
      for (let p = el.parentElement; p; p = p.parentElement) {
        const ox = getComputedStyle(p).overflowX
        if (ox === 'auto' || ox === 'scroll' || ox === 'hidden' || ox === 'clip') return true
      }
      return false
    }

    if (document.documentElement.scrollWidth > vw + 1)
      problems.push(`page scrolls horizontally (${document.documentElement.scrollWidth}px wide, viewport ${vw}px)`)

    const offenders = []
    for (const el of document.body.querySelectorAll('*')) {
      const r = el.getBoundingClientRect()
      if (r.width < 2 || r.height < 2) continue
      if ((r.right > vw + 1 || r.left < -1) && !inScroller(el)) {
        const parentOff = offenders.some((o) => o.contains(el))
        if (!parentOff) offenders.push(el)
      }
    }
    for (const el of offenders.slice(0, 5)) problems.push(`sticks out of viewport: ${describe(el)}`)

    for (const el of document.querySelectorAll(
      '[role=menu],[role=listbox],[role=dialog],[data-slot=popover-content],[data-slot=dropdown-menu-content]',
    )) {
      const r = el.getBoundingClientRect()
      if (r.width < 2) continue
      if (r.left < -1 || r.top < -1 || r.right > vw + 1 || r.bottom > vh + 1)
        problems.push(`popup off-screen: ${describe(el)} (${Math.round(r.left)},${Math.round(r.top)} → ${Math.round(r.right)},${Math.round(r.bottom)})`)
    }

    // Clipped text: content wider/taller than its box, hidden, without an ellipsis.
    for (const el of document.body.querySelectorAll('h1,h2,h3,p,span,a,button,label,td,th,li,div')) {
      if (!el.childNodes.length || ![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue
      const cs = getComputedStyle(el)
      const hiddenX = ['hidden', 'clip'].includes(cs.overflowX)
      const hiddenY = ['hidden', 'clip'].includes(cs.overflowY)
      const clippedX = hiddenX && el.scrollWidth > el.clientWidth + 1 && cs.textOverflow !== 'ellipsis'
      const clippedY = hiddenY && el.scrollHeight > el.clientHeight + 2 && !cs.webkitLineClamp?.match(/\d/)
      // clientWidth <= 1: screen-reader-only labels (.sr-only) are clipped on purpose.
      if ((clippedX || clippedY) && el.clientWidth > 1) problems.push(`text clipped: ${describe(el)}`)
    }

    const dir = document.documentElement.dir
    const lang = document.documentElement.lang
    if ((lang === 'ur') !== (dir === 'rtl')) problems.push(`direction mismatch: lang=${lang} dir=${dir}`)
    return { problems: [...new Set(problems)], dir, dark: document.documentElement.classList.contains('dark') }
  })
}

async function settle(page) {
  await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {})
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(250)
}

async function shot(page, dir, name, { fullPage = true, expect } = {}) {
  await settle(page)
  mkdirSync(dir, { recursive: true })
  const file = path.join(dir, `${name}.png`)
  await page.screenshot({ path: file, fullPage })
  report.shots++
  const result = await inspect(page)
  const problems = [...result.problems]
  if (expect?.theme && result.dark !== (expect.theme === 'dark')) problems.push(`theme not applied (expected ${expect.theme})`)
  if (problems.length) report.issues.push({ file: path.relative(OUT, file), problems })
}

function watchConsole(page, label) {
  page.on('console', (msg) => {
    // The deliberate wrong-password step answers 401; Chrome logs that as a console error.
    if (page.expectFailedLogin && msg.text().includes('401')) return
    if (msg.type() === 'error') report.consoleErrors.push({ where: `${label} ${page.url()}`, text: msg.text().slice(0, 300) })
  })
  page.on('pageerror', (err) => report.consoleErrors.push({ where: `${label} ${page.url()}`, text: `pageerror: ${err.message}` }))
  page.on('response', (res) => {
    if (res.status() >= 500) report.consoleErrors.push({ where: `${label} ${page.url()}`, text: `HTTP ${res.status()} ${res.url()}` })
  })
}

// ---------------------------------------------------------------- scenarios
async function publicPages(browser, vpName, vp) {
  for (const theme of THEMES) {
    for (const lang of LANGS) {
      const ctx = await browser.newContext(vp)
      await ctx.addInitScript(
        ([t, l]) => {
          localStorage.setItem('crm.theme', t)
          localStorage.setItem('crm.language', l)
        },
        [theme, lang],
      )
      const page = await ctx.newPage()
      watchConsole(page, `public/${vpName}/${theme}-${lang}`)
      const dir = path.join(OUT, vpName, `${theme}-${lang}`)
      await page.goto(`${BASE}/login`)
      await shot(page, dir, 'public-login', { expect: { theme } })
      await page.fill('#email', 'nobody@office.test')
      await page.fill('#password', 'wrong-password')
      page.expectFailedLogin = true
      await page.click('button[type=submit]')
      await page.waitForSelector('[data-slot=alert]')
      page.expectFailedLogin = false
      await shot(page, dir, 'public-login-error')
      await page.fill('#email', TWO_FA_USER)
      await page.fill('#password', PASSWORD)
      await page.click('button[type=submit]')
      await page.waitForSelector('#code')
      await shot(page, dir, 'public-login-otp')
      await page.goto(`${BASE}/forgot-password`)
      await shot(page, dir, 'public-forgot-password')
      await page.goto(`${BASE}/reset-password?uid=MQ&token=abc`)
      await shot(page, dir, 'public-reset-password')
      await page.goto(`${BASE}/reset-password`)
      await shot(page, dir, 'public-reset-password-invalid')
      await ctx.close()
    }
  }
}

async function rolePages(browser, role, vpName, vp, data) {
  const email = ROLES[role]
  const token = await apiLogin(email)
  const ctx = await browser.newContext(vp)
  const page = await ctx.newPage()
  watchConsole(page, `${role}/${vpName}`)
  const isPhone = vpName === 'phone'

  await page.goto(`${BASE}/login`)
  await page.fill('#email', email)
  await page.fill('#password', PASSWORD)
  await page.click('button[type=submit]')
  await page.waitForURL(`${BASE}/`)

  for (const theme of THEMES) {
    for (const lang of LANGS) {
      await call(token, 'PATCH', '/auth/me/', { theme, language: lang })
      const dir = path.join(OUT, vpName, `${theme}-${lang}`)
      const s = (name, opts) => shot(page, dir, `${role}-${name}`, { expect: { theme }, ...opts })
      const go = async (url) => {
        await page.goto(`${BASE}${url}`)
        await page.waitForSelector('main')
      }

      await go('/')
      await s('dashboard')

      // Popups from the top bar
      await page.getByRole('button', { name: /notifications|اطلاعات/i }).first().click()
      await s('popup-notifications', { fullPage: false })
      await page.keyboard.press('Escape')
      await page.locator('header button[aria-haspopup]:visible').last().click() // user menu
      await s('popup-user-menu', { fullPage: false })
      await page.keyboard.press('Escape')
      await page.locator('button[aria-haspopup]:visible:has(svg.lucide-plus)').first().click() // quick add (top bar on desktop, page header on phone)
      await s('popup-quick-add', { fullPage: false })
      await page.keyboard.press('Escape')
      await page.keyboard.press('Control+k')
      await page.keyboard.type('sa')
      await page.waitForTimeout(700)
      await s('popup-search', { fullPage: false })
      await page.keyboard.press('Escape')
      if (isPhone) {
        await page.locator('nav.fixed button').last().click() // "More"
        await s('popup-more-sheet', { fullPage: false })
        await page.keyboard.press('Escape')
      }

      await go('/team')
      await s('team')
      const z = data.users['zainab@office.test']
      await go(`/team?department=${data.depts.Sales.id}&user=${z.id}`)
      await s('team-spotlight')

      await go('/notifications')
      await s('notifications')
      for (const tab of ['profile', 'appearance', 'security', 'notifications']) {
        await go(`/settings?tab=${tab}`)
        await s(`settings-${tab}`)
      }

      if (role === 'admin') {
        await go('/admin/users')
        await s('admin-users')
        await page.locator('main [aria-haspopup]:visible').nth(1).click() // first row actions (0 = role filter)
        await s('popup-user-actions', { fullPage: false })
        await page.getByRole('menuitem').first().click() // Edit
        await page.waitForSelector('[role=dialog]')
        await s('dialog-user-edit', { fullPage: false })
        await page.locator('[role=dialog] #u-dept').click() // (own role select is disabled by design)
        await s('popup-department-select', { fullPage: false })
        await page.keyboard.press('Escape')
        await page.keyboard.press('Escape')
        await page.locator('main [aria-haspopup]:visible').nth(2).click() // second row actions
        await page.getByRole('menuitem').last().click() // Delete -> confirm dialog
        await page.waitForSelector('[role=dialog]')
        await s('dialog-confirm-delete', { fullPage: false })
        await page.keyboard.press('Escape')

        await go('/admin/departments')
        await s('admin-departments')
        await go('/admin/organization')
        await s('admin-organization')
        await go('/admin/audit-log')
        await s('admin-audit-log')
        await go('/admin/system')
        await page.waitForSelector('main [data-slot=card]')
        await s('admin-system')
      } else {
        await go('/admin/users')
        await s('admin-users-denied')
      }
    }
  }
  await ctx.close()
}

// ---------------------------------------------------------------- main
const browser = await chromium.launch({ channel: 'chrome' })
try {
  const data = await prepareData()
  for (const [vpName, vp] of Object.entries(VIEWPORTS)) {
    if (!ONLY || ONLY === 'public') await publicPages(browser, vpName, vp)
    for (const role of Object.keys(ROLES)) {
      if (ONLY && ONLY !== role) continue
      await rolePages(browser, role, vpName, vp, data)
      console.log(`done ${role} ${vpName}`)
    }
  }
} finally {
  await browser.close()
  // Leave the demo users in their default language/theme.
  for (const email of Object.values(ROLES)) {
    const token = await apiLogin(email).catch(() => null)
    if (token) await call(token, 'PATCH', '/auth/me/', { theme: 'system', language: 'en' })
  }
  mkdirSync(OUT, { recursive: true })
  writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2))
  console.log(`${report.shots} screenshots, ${report.issues.length} with issues, ${report.consoleErrors.length} console errors`)
  console.log(`report: ${path.join(OUT, 'report.json')}`)
}
