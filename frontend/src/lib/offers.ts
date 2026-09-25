/** Offers (schemes) as line discounts - mirrors app.services.offers.apply_offers exactly (same test vectors). */
import type { OffersConfig } from './types'

export interface OfferLine { sku: string; category?: string | null; quantity: number; unit_price: number; discount_pct?: number }
export type OfferResult<T> = { lines: (T & { discount_pct: number; offer: string | null })[]; applied: string[] }

const r2 = (n: number) => Math.round(n * 100) / 100

export function applyOffers<T extends OfferLine>(lines: T[], cfg: Pick<OffersConfig, 'enabled' | 'offers'> | undefined): OfferResult<T> {
  const out = lines.map((l) => ({ ...l, discount_pct: Number(l.discount_pct ?? 0), offer: null as string | null }))
  if (!cfg?.enabled) return { lines: out, applied: [] }
  const offers = cfg.offers.filter((o) => o.active !== false)
  const applied: string[] = []

  for (const o of offers) {
    if (o.type === 'item_percent') {
      let hit = false
      for (const l of out) {
        const match = (o.sku && l.sku.toUpperCase() === o.sku) || (o.category && (l.category ?? '').toLowerCase() === o.category.toLowerCase())
        if (match && (o.percent ?? 0) > l.discount_pct) {
          l.discount_pct = r2(o.percent ?? 0)
          l.offer = o.label
          hit = true
        }
      }
      if (hit) applied.push(o.label)
    } else if (o.type === 'buy_x_get_y') {
      const buy = o.buy ?? 1
      const free = o.free ?? 1
      for (const l of out) {
        const qty = Math.trunc(l.quantity)
        if (l.sku.toUpperCase() !== o.sku || qty < buy + free) continue
        const freeUnits = Math.floor(qty / (buy + free)) * free
        const pct = r2((freeUnits / qty) * 100)
        if (pct > l.discount_pct) {
          l.discount_pct = pct
          l.offer = o.label
          applied.push(o.label)
        }
      }
    }
  }

  const gross = out.reduce((s, l) => s + l.unit_price * l.quantity * (1 - l.discount_pct / 100), 0)
  const best = offers
    .filter((o) => o.type === 'bill_percent' && gross >= (o.min_amount ?? 0))
    .reduce<(typeof offers)[number] | null>((b, o) => (!b || (o.percent ?? 0) > (b.percent ?? 0) ? o : b), null)
  if (best) {
    for (const l of out) {
      l.discount_pct = r2(100 - ((100 - l.discount_pct) * (100 - (best.percent ?? 0))) / 100)
      l.offer = l.offer ? `${l.offer} + ${best.label}` : best.label
    }
    applied.push(best.label)
  }
  return { lines: out, applied }
}

export const pointsFor = (amount: number, earnPer100: number) => Math.max(0, Math.floor((amount / 100) * earnPer100 + 1e-9))
