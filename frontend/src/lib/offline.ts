/** Offline billing: bills made while the internet / server is down wait here and sync by themselves later.
 *  Each bill carries a `client_ref`, so a bill that is sent twice is still saved only once. */
import { useSyncExternalStore } from 'react'
import { ApiError, get, post } from './api'

const QUEUE_KEY = 'ii-offline-bills'
const SEQ_KEY = 'ii-offline-seq'
const CACHE_PREFIX = 'ii-cache:'

export interface QueuedBill {
  client_ref: string
  number: string // provisional, e.g. OFF-3 - the real bill number comes on sync
  created_at: string
  total: number
  customer: string
  lines: { name: string; quantity: number; total: number }[] // for the provisional receipt
  payload: Record<string, unknown>
  error?: string
}

export const isNetworkError = (e: unknown) =>
  e instanceof TypeError || (e instanceof ApiError && [0, 502, 503, 504].includes(e.status))

const read = <T,>(key: string, fallback: T): T => {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}
const write = (key: string, value: unknown) => {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* storage full or blocked - nothing more we can do */
  }
}

let queue: QueuedBill[] = read(QUEUE_KEY, [])
const listeners = new Set<() => void>()
const setQueue = (next: QueuedBill[]) => {
  queue = next
  write(QUEUE_KEY, next)
  listeners.forEach((fn) => fn())
}

export const useOfflineQueue = () =>
  useSyncExternalStore(
    (fn) => {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
    () => queue,
  )

const newRef = () => (typeof globalThis.crypto?.randomUUID === 'function' && globalThis.isSecureContext ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`)

export function queueBill(payload: Record<string, unknown>, total: number, customer: string, lines: QueuedBill['lines'] = []): QueuedBill {
  const seq = read<number>(SEQ_KEY, 0) + 1
  write(SEQ_KEY, seq)
  const bill: QueuedBill = { client_ref: newRef(), number: `OFF-${seq}`, created_at: new Date().toISOString(), total, customer, lines, payload }
  setQueue([...queue, bill])
  return bill
}

export const removeBill = (ref: string) => setQueue(queue.filter((b) => b.client_ref !== ref))
export const retryBill = (ref: string) => setQueue(queue.map((b) => (b.client_ref === ref ? { ...b, error: undefined } : b)))

let syncing: Promise<number> | null = null

/** Send waiting bills in order. Returns how many were saved. Stops at the first network error. */
export function syncQueue(): Promise<number> {
  if (syncing) return syncing
  syncing = (async () => {
    let saved = 0
    for (const bill of [...queue]) {
      if (bill.error) continue
      try {
        await post('/api/invoices', { ...bill.payload, client_ref: bill.client_ref, created_at: bill.created_at })
        setQueue(queue.filter((b) => b.client_ref !== bill.client_ref))
        saved += 1
      } catch (e) {
        if (isNetworkError(e)) break
        const msg = e instanceof Error ? e.message : String(e)
        setQueue(queue.map((b) => (b.client_ref === bill.client_ref ? { ...b, error: msg } : b)))
      }
    }
    return saved
  })().finally(() => {
    syncing = null
  })
  return syncing
}

/** GET that remembers the last answer, so billing still opens when the server can't be reached. */
export async function cachedGet<T>(path: string): Promise<T> {
  try {
    const data = await get<T>(path)
    write(CACHE_PREFIX + path, data)
    return data
  } catch (e) {
    if (isNetworkError(e)) {
      const cached = read<T | null>(CACHE_PREFIX + path, null)
      if (cached !== null) return cached
    }
    throw e
  }
}
