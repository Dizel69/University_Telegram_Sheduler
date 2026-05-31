import React, { useEffect, useState, useCallback } from 'react'
import { getResolvedTheme, getStoredTheme, setThemePreference } from './theme'

export default function ThemeToggle() {
  const [isDark, setIsDark] = useState(() => getResolvedTheme() === 'dark')

  useEffect(() => {
    const root = document.documentElement
    const sync = () => setIsDark(root.getAttribute('data-theme') === 'dark')
    sync()
    const obs = new MutationObserver(sync)
    obs.observe(root, { attributes: true, attributeFilter: ['data-theme'] })
    return () => obs.disconnect()
  }, [])

  const toggle = useCallback(() => {
    const next = isDark ? 'light' : 'dark'
    setThemePreference(next)
    setIsDark(next === 'dark')
  }, [isDark])

  const followsSystem = !getStoredTheme() || getStoredTheme() === 'system'

  return (
    <button
      type="button"
      className={`theme-toggle${isDark ? ' theme-toggle--dark' : ''}`}
      onClick={toggle}
      role="switch"
      aria-checked={isDark}
      aria-label={isDark ? 'Тёмная тема, переключить на светлую' : 'Светлая тема, переключить на тёмную'}
      title={followsSystem ? 'Следует системной теме. Нажмите, чтобы зафиксировать' : 'Переключить тему'}
    >
      <span className="theme-toggle-track" aria-hidden="true">
        <span className="theme-toggle-icons">
          <span className="theme-toggle-icon theme-toggle-icon--moon">🌙</span>
          <span className="theme-toggle-icon theme-toggle-icon--sun">☀️</span>
        </span>
        <span className="theme-toggle-stars" aria-hidden="true">
          <i /><i /><i />
        </span>
        <span className="theme-toggle-thumb" aria-hidden="true" />
      </span>
    </button>
  )
}
