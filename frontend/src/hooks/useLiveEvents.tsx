import { useQueryClient, type QueryKey } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { tokenStore } from '@/lib/api'
import type { LiveEvent } from '@/lib/types'
import { keys } from './queries'

interface LiveState {
  events: LiveEvent[]
  connected: boolean
}

const LiveContext = createContext<LiveState>({ events: [], connected: false })

/** Which cached queries each event family makes stale. */
const INVALIDATES: [RegExp, QueryKey[]][] = [
  [/^stock\.|^catalog\.|^product\./, [keys.products, keys.dashboard, keys.alerts, keys.reorder, ['products'], ['health'], ['markdowns']]],
  [/^po\./, [['purchase-orders'], keys.dashboard, keys.reorder, keys.suppliersScores]],
  [/^approval\./, [['approvals'], keys.conversations]],
  [/^count\./, [keys.counts]],
  [/^report\./, [keys.reports]],
  [/^anomaly\.|^job\./, [keys.alerts, keys.jobs]],
  [/^agent\.run/, [keys.conversations, ['traces']]],
  [/^hook\.|^autopilot\./, [keys.hooks, keys.automation]],
  [/^webhook\./, [keys.webhooks]],
]

function notify(e: LiveEvent) {
  const p = e.payload as Record<string, unknown>
  switch (e.type) {
    case 'stock.out':
      toast.error(`${p.name} is out of stock`, { description: `${p.sku} · suggested order ${p.suggested_order_qty}` })
      break
    case 'stock.low':
      toast.warning(`${p.name} is running low`, { description: `${p.on_hand} on hand · reorder point ${p.reorder_point}` })
      break
    case 'approval.requested':
      toast.info(`Approval needed: ${String(p.tool).replace(/_/g, ' ')}`, { description: `Requested by the ${p.agent} agent` })
      break
    case 'autopilot.triggered':
      toast(`🤖 Autopilot is drafting a PO for ${p.name}`)
      break
    case 'po.created':
      if (String(e.source).startsWith('agent:')) toast.success(`${e.source.slice(6)} agent drafted ${p.number}`)
      break
    case 'report.created':
      toast.success('New AI briefing is ready')
      break
  }
}

export function LiveEventsProvider({ children }: { children: ReactNode }) {
  const [events, setEvents] = useState<LiveEvent[]>([])
  const [connected, setConnected] = useState(false)
  const qc = useQueryClient()
  const pending = useRef(new Set<string>())
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    const token = tokenStore.get()
    if (!token) return
    let source: EventSource | null = null
    let retry: number | undefined
    let closed = false

    const flush = () => {
      pending.current.forEach((k) => qc.invalidateQueries({ queryKey: JSON.parse(k) }))
      pending.current.clear()
    }

    const connect = () => {
      source = new EventSource(`/api/events/stream?access_token=${encodeURIComponent(token)}`)
      source.addEventListener('ready', () => setConnected(true))
      source.onmessage = (msg) => {
        const event = JSON.parse(msg.data) as LiveEvent
        setEvents((prev) => [event, ...prev].slice(0, 150))
        for (const [re, qks] of INVALIDATES) if (re.test(event.type)) qks.forEach((k) => pending.current.add(JSON.stringify(k)))
        window.clearTimeout(timer.current)
        timer.current = window.setTimeout(flush, 400) // coalesce bursts (e.g. PO receipts)
        notify(event)
      }
      source.onerror = () => {
        setConnected(false)
        source?.close()
        if (!closed) retry = window.setTimeout(connect, 3000)
      }
    }
    connect()
    return () => {
      closed = true
      window.clearTimeout(retry)
      window.clearTimeout(timer.current)
      source?.close()
    }
  }, [qc])

  return <LiveContext.Provider value={{ events, connected }}>{children}</LiveContext.Provider>
}

export const useLiveEvents = () => useContext(LiveContext)
