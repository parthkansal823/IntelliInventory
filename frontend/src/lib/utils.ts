import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs))

// Indian Rupees with lakh/crore grouping: ₹1,53,68,990 · compact ₹1.5Cr / ₹2.4L
const inr0 = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })
const inr2 = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 })
const compactInr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', notation: 'compact', minimumFractionDigits: 0, maximumFractionDigits: 1 })
const num = new Intl.NumberFormat('en-IN')
const compact = new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 })

export const money = (v: number | null | undefined) => (v == null ? '—' : Math.abs(v) >= 100 ? inr0.format(v) : inr2.format(v))
export const moneyCompact = (v: number | null | undefined) => (v == null ? '—' : compactInr.format(v))
export const number = (v: number | null | undefined) => (v == null ? '—' : num.format(v))
export const numberCompact = (v: number | null | undefined) => (v == null ? '—' : compact.format(v))
export const pct = (v: number | null | undefined, digits = 1) => (v == null ? '—' : `${v.toFixed(digits)}%`)

/** India-only app: every date/time is shown in IST with Indian formatting. */
export const IST = 'Asia/Kolkata'

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 45) return 'just now'
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
  if (diff < 86400 * 7) return `${Math.round(diff / 86400)}d ago`
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: IST })
}

export const shortDate = (iso: string) => new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: IST })
export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZone: IST })
export const timeOnly = (iso: string | Date) => new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', second: '2-digit', timeZone: IST })
export const longDate = (iso: string) => new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric', timeZone: IST })

export const titleCase = (s: string) => s.replace(/[_.]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

export function greeting(): string {
  const h = Number(new Date().toLocaleString('en-IN', { hour: 'numeric', hourCycle: 'h23', timeZone: IST }))
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export function actorLabel(actor: string | null | undefined): { label: string; isAgent: boolean } {
  if (!actor) return { label: '—', isAgent: false }
  if (actor.startsWith('agent:')) return { label: actor.slice(6).split('~')[0], isAgent: true }
  if (actor.startsWith('user:')) return { label: actor.slice(5).split('@')[0], isAgent: false }
  return { label: actor.replace('system:', ''), isAgent: false }
}
