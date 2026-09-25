import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyOffers, pointsFor } from './offers'
import type { Offer } from './types'

const OFFERS: Offer[] = [
  { type: 'buy_x_get_y', label: 'SNK-404: buy 2 get 1 free', active: true, sku: 'SNK-404', buy: 2, free: 1 },
  { type: 'item_percent', label: '10% off Personal Care', active: true, category: 'Personal Care', sku: null, percent: 10 },
  { type: 'bill_percent', label: '5% off above Rs 500', active: true, min_amount: 500, percent: 5 },
]
const LINES = [
  { sku: 'SNK-404', category: 'Snacks & Biscuits', quantity: 6, unit_price: 45 },
  { sku: 'PRC-602', category: 'Personal Care', quantity: 1, unit_price: 100, discount_pct: 20 },
  { sku: 'ATA-101', category: 'Atta Rice & Dal', quantity: 1, unit_price: 420 },
]

describe('applyOffers (mirror of app.services.offers.apply_offers)', () => {
  it('matches the backend test vectors', () => {
    const out = applyOffers(LINES, { enabled: true, offers: OFFERS })
    expect(out.lines.map((l) => l.discount_pct)).toEqual([36.66, 24, 5])
    expect(out.applied).toHaveLength(2)
  })
  it('does nothing when offers are switched off', () => {
    expect(applyOffers(LINES, { enabled: false, offers: OFFERS }).lines[0].discount_pct).toBe(0)
    expect(applyOffers(LINES, undefined).applied).toEqual([])
  })
  it('earns whole points only', () => {
    expect(pointsFor(399, 1)).toBe(3)
    expect(pointsFor(500, 2)).toBe(10)
  })
})

describe('offline bill queue', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })
  it('keeps bills when the server is unreachable and sends each once when it is back', async () => {
    vi.resetModules()
    const offline = await import('./offline')
    const bill = offline.queueBill({ items: [{ product_id: 1, quantity: 2 }] }, 90, 'Walk-in')
    expect(bill.number).toBe('OFF-1')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    expect(await offline.syncQueue()).toBe(0)
    expect(JSON.parse(localStorage.getItem('ii-offline-bills') ?? '[]')).toHaveLength(1)

    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 7, number: 'KGS/26-27/00099' }), { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await offline.syncQueue()).toBe(1)
    const sent = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(sent.client_ref).toBe(bill.client_ref)
    expect(JSON.parse(localStorage.getItem('ii-offline-bills') ?? '[]')).toHaveLength(0)
  })
  it('marks a bill the server rejects instead of retrying it forever', async () => {
    vi.resetModules()
    const offline = await import('./offline')
    offline.queueBill({ items: [] }, 10, 'Walk-in')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Only 1 in stock' }), { status: 400 })))
    await offline.syncQueue()
    const [saved] = JSON.parse(localStorage.getItem('ii-offline-bills') ?? '[]')
    expect(saved.error).toBe('Only 1 in stock')
  })
  it('isNetworkError treats gateway errors as offline', async () => {
    const { isNetworkError } = await import('./offline')
    const { ApiError } = await import('./api')
    expect(isNetworkError(new TypeError('x'))).toBe(true)
    expect(isNetworkError(new ApiError(503, 'x'))).toBe(true)
    expect(isNetworkError(new ApiError(400, 'x'))).toBe(false)
  })
})
