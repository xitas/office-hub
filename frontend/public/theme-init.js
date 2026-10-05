// Apply theme and direction before first paint (same storage keys as the React providers).
// Kept as a static file (not inline) so the site can use a strict CSP: script-src 'self'.
try {
  var t = localStorage.getItem('crm.theme') || 'system'
  var dark = t === 'dark' || (t === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  if (dark) document.documentElement.classList.add('dark')
  if (localStorage.getItem('crm.language') === 'ur') {
    document.documentElement.lang = 'ur'
    document.documentElement.dir = 'rtl'
  }
} catch {
  // storage unavailable (private mode): fall back to defaults
}
