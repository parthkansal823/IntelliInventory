/** Offline fallback for quick-type billing ("2 atta 1 maggi") when the server's parser can't be reached.
 *  Simpler than app.services.voice (no Devanagari), but good enough to keep the counter running. */
import type { ProductRow } from './types'

const NUMBERS: Record<string, number> = {
  ek: 1, one: 1, do: 2, two: 2, teen: 3, three: 3, char: 4, chaar: 4, four: 4, panch: 5, paanch: 5, five: 5,
  chhe: 6, six: 6, saat: 7, seven: 7, aath: 8, eight: 8, nau: 9, nine: 9, das: 10, ten: 10,
}
const ALIASES: Record<string, string> = {
  aata: 'atta', cheeni: 'sugar', chini: 'sugar', shakkar: 'sugar', namak: 'salt', maggi: 'noodles', sabun: 'soap',
  tel: 'oil', chawal: 'rice', chaval: 'rice', daal: 'dal', chai: 'tea', patti: 'tea', biskut: 'biscuits',
  biscuit: 'biscuits', makhan: 'butter', doodh: 'milk', surf: 'detergent', kapoor: 'camphor', diya: 'diya',
}
const FILLER = new Set(['kilo', 'kg', 'g', 'gm', 'gram', 'packet', 'pack', 'pkt', 'litre', 'liter', 'l', 'bottle', 'piece', 'pcs', 'ka', 'ki', 'ke', 'wala', 'wali', 'de', 'dena', 'please'])
const SEPARATORS = new Set(['aur', 'and', 'or', 'phir'])

export interface LocalMatch { product: ProductRow; quantity: number }

function find(words: string[], products: ProductRow[]): ProductRow | undefined {
  const active = products.filter((p) => p.is_active)
  const sku = active.find((p) => p.sku.toLowerCase() === words.join('-') || p.sku.toLowerCase() === words.join(''))
  if (sku) return sku
  const terms = words.map((w) => ALIASES[w] ?? w).filter((w) => w.length >= 3)
  let best: ProductRow | undefined
  let bestHits = 0
  for (const p of active) {
    const name = p.name.toLowerCase()
    const hits = terms.filter((t) => name.includes(t)).length
    if (hits > bestHits) {
      best = p
      bestHits = hits
    }
  }
  return best
}

export function parseLocal(text: string, products: ProductRow[]): { items: LocalMatch[]; unmatched: string[] } {
  const tokens = text.toLowerCase().match(/[a-z]{3}-\d{3,4}|[a-z]+|\d+|,/g) ?? []
  const phrases: { words: string[]; qty: number }[] = []
  let words: string[] = []
  let qty: number | null = null
  const flush = (q: number | null) => {
    if (words.length) phrases.push({ words, qty: Math.max(1, q ?? 1) })
    words = []
  }
  tokens.forEach((tok, i) => {
    const next = tokens[i + 1]
    if (tok === 'do' && (next === undefined || tokens[i - 1] === 'de')) return // "de do" = please give
    const n = /^\d+$/.test(tok) ? Number(tok) : NUMBERS[tok]
    if (n !== undefined) {
      if (words.length) {
        flush(qty ?? n)
        qty = qty === null ? null : n
      } else qty = n
      return
    }
    if (tok === ',' || SEPARATORS.has(tok)) {
      flush(qty)
      qty = null
      return
    }
    if (!FILLER.has(tok)) words.push(tok)
  })
  flush(qty)

  const items: LocalMatch[] = []
  const unmatched: string[] = []
  for (const ph of phrases) {
    const p = find(ph.words, products)
    if (!p) unmatched.push(ph.words.join(' '))
    else {
      const seen = items.find((i) => i.product.id === p.id)
      if (seen) seen.quantity += ph.qty
      else items.push({ product: p, quantity: ph.qty })
    }
  }
  return { items, unmatched }
}
