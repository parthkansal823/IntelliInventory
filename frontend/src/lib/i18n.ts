/** Tiny English / हिंदी switch. Strings are written in English and looked up in HI (missing ones stay English). */
import { useCallback, useSyncExternalStore } from 'react'
import { HI } from './hi'

export type Lang = 'en' | 'hi'
const KEY = 'ii-lang'
const listeners = new Set<() => void>()

function read(): Lang {
  try {
    return localStorage.getItem(KEY) === 'hi' ? 'hi' : 'en'
  } catch {
    return 'en'
  }
}

let current: Lang = read()
if (typeof document !== 'undefined') document.documentElement.lang = current === 'hi' ? 'hi' : 'en-IN'

export function setLang(lang: Lang) {
  current = lang
  try {
    localStorage.setItem(KEY, lang)
  } catch {
    /* private mode - still switches for this visit */
  }
  document.documentElement.lang = lang === 'hi' ? 'hi' : 'en-IN'
  listeners.forEach((fn) => fn())
}

const subscribe = (fn: () => void) => {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export const useLang = () => useSyncExternalStore(subscribe, () => current, () => current)

function translate(lang: Lang, text: string, vars?: Record<string, string | number>): string {
  let out = lang === 'hi' ? (HI[text] ?? text) : text
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.replaceAll(`{${k}}`, String(v))
  return out
}

/** `const t = useT(); t('Save bill')` - re-renders when the language changes. `{name}` placeholders via vars. */
export function useT() {
  const lang = useLang()
  return useCallback((text: string, vars?: Record<string, string | number>) => translate(lang, text, vars), [lang])
}

/** For code outside components (toasts, print, WhatsApp text). */
export const tr = (text: string, vars?: Record<string, string | number>) => translate(current, text, vars)
