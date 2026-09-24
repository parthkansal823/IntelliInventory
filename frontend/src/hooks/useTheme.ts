import { useCallback, useEffect, useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark' | 'system'
const KEY = 'ii-theme'
const listeners = new Set<() => void>()

function read(): Theme {
  try {
    return (localStorage.getItem(KEY) as Theme) || 'system'
  } catch {
    return 'system'
  }
}

function apply(theme: Theme) {
  const dark = theme === 'dark' || (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
}

export function useTheme() {
  const theme = useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    read,
    () => 'system' as Theme,
  )

  useEffect(() => {
    apply(theme)
    if (theme !== 'system') return
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => apply('system')
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [theme])

  const setTheme = useCallback((next: Theme) => {
    try {
      localStorage.setItem(KEY, next)
    } catch {
      /* private mode - theme still applies for this session */
    }
    apply(next)
    listeners.forEach((l) => l())
  }, [])

  const isDark = theme === 'dark' || (theme === 'system' && typeof matchMedia !== 'undefined' && matchMedia('(prefers-color-scheme: dark)').matches)
  return { theme, setTheme, isDark }
}
