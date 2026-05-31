const STORAGE_KEY = 'app-theme'

/** @returns {'light' | 'dark' | 'system' | null} */
export function getStoredTheme() {
  const v = localStorage.getItem(STORAGE_KEY)
  if (v === 'light' || v === 'dark' || v === 'system') return v
  return null
}

/** @param {'light' | 'dark' | 'system' | null} stored */
export function resolveTheme(stored) {
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** @param {'light' | 'dark'} theme */
export function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme)
}

export function getResolvedTheme() {
  return resolveTheme(getStoredTheme())
}

/** @param {'light' | 'dark'} preference */
export function setThemePreference(preference) {
  localStorage.setItem(STORAGE_KEY, preference)
  applyTheme(preference)
}

export function initTheme() {
  applyTheme(getResolvedTheme())

  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  mq.addEventListener('change', () => {
    const stored = getStoredTheme()
    if (!stored || stored === 'system') {
      applyTheme(resolveTheme('system'))
    }
  })
}
