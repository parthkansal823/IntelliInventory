import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs))

const usd0 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const usd2 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
const compactUsd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 })
const num = new Intl.NumberFormat('en-US')
const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })

export const money = (v: number | null | undefined) => (v == null ? '—' : Math.abs(v) >= 100 ? usd0.format(v) : usd2.format(v))
export const moneyCompact = (v: number | null | undefined) => (v == null ? '—' : compactUsd.format(v))
export const number = (v: number | null | undefined) => (v == null ? '—' : num.format(v))
export const numberCompact = (v: number | null | undefined) => (v == null ? '—' : compact.format(v))
export const pct = (v: number | null | undefined, digits = 1) => (v == null ? '—' : `${v.toFixed(digits)}%`)

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 45) return 'just now'
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`
  if (diff < 86400 * 7) return `${Math.round(diff / 86400)}d ago`
  return new Date(iso).toLocaleDateString()
}

export const shortDate = (iso: string) => new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })

export const titleCase = (s: string) => s.replace(/[_.]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

export function greeting(): string {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export function actorLabel(actor: string | null | undefined): { label: string; isAgent: boolean } {
  if (!actor) return { label: '—', isAgent: false }
  if (actor.startsWith('agent:')) return { label: actor.slice(6).split('~')[0], isAgent: true }
  if (actor.startsWith('user:')) return { label: actor.slice(5).split('@')[0], isAgent: false }
  return { label: actor.replace('system:', ''), isAgent: false }
}
