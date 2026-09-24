import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, get, readSSE, tokenStore } from '@/lib/api'
import type { ChatItem } from '@/lib/types'
import { keys } from './queries'

type StreamEvent =
  | ChatItem
  | { type: 'text' | 'thinking'; agent: string; depth: number; delta: string }
  | { type: 'conversation'; id: string; title: string; agent: string; provider: string; model: string | null; run_id: string }
  | { type: 'done'; conversation_id: string; trace_id: string; status: string; usage: { input_tokens: number; output_tokens: number } }

export interface ChatMeta {
  conversationId: string | null
  title?: string
  provider?: string
  model?: string | null
  lastTraceId?: string
  usage?: { input_tokens: number; output_tokens: number }
}

/** Mirror of the backend's `_record_display`: merge streamed deltas into display items. */
export function applyEvent(items: ChatItem[], event: StreamEvent): ChatItem[] {
  if (event.type === 'conversation' || event.type === 'done') return items
  if ((event.type === 'text' || event.type === 'thinking') && 'delta' in event) {
    const last = items[items.length - 1]
    if (last && last.type === event.type && last.agent === event.agent && last.depth === event.depth) {
      return [...items.slice(0, -1), { ...last, text: last.text + event.delta }]
    }
    return [...items, { type: event.type, agent: event.agent, depth: event.depth, text: event.delta }]
  }
  return [...items, event as ChatItem]
}

export function useAgentChat(initialConversationId: string | null) {
  const [items, setItems] = useState<ChatItem[]>([])
  const [meta, setMeta] = useState<ChatMeta>({ conversationId: initialConversationId })
  const [streaming, setStreaming] = useState(false)
  const [loading, setLoading] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const qc = useQueryClient()

  const load = useCallback(async (conversationId: string | null) => {
    abort.current?.abort()
    setStreaming(false)
    setMeta({ conversationId })
    if (!conversationId) {
      setItems([])
      return
    }
    setLoading(true)
    try {
      const conv = await get<{ id: string; title: string; provider: string; display: ChatItem[] }>(`/api/agents/conversations/${conversationId}`)
      setItems(conv.display)
      setMeta({ conversationId: conv.id, title: conv.title, provider: conv.provider })
    } catch {
      setItems([])
      setMeta({ conversationId: null })
    } finally {
      setLoading(false)
    }
  }, [])

  // Load when the caller switches conversations - but not when the URL merely catches up with the
  // conversation this hook just created (that would abort the live stream).
  const currentId = useRef<string | null>(meta.conversationId)
  currentId.current = meta.conversationId
  const loaded = useRef(false)
  useEffect(() => {
    if (loaded.current && initialConversationId === currentId.current) return
    loaded.current = true
    load(initialConversationId)
  }, [initialConversationId, load])

  const send = useCallback(
    async (message: string, opts: { agent?: string; provider?: string } = {}) => {
      if (!message.trim() || streaming) return
      const controller = new AbortController()
      abort.current = controller
      setStreaming(true)
      setItems((prev) => [...prev, { type: 'user', text: message, ts: new Date().toISOString() }])
      try {
        const res = await fetch('/api/agents/chat', {
          method: 'POST',
          signal: controller.signal,
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${tokenStore.get() ?? ''}` },
          body: JSON.stringify({
            message,
            conversation_id: meta.conversationId,
            agent: opts.agent,
            provider: opts.provider === 'auto' ? undefined : opts.provider,
          }),
        })
        if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail ?? res.statusText)
        for await (const raw of readSSE(res)) {
          const event = raw as StreamEvent
          if (event.type === 'conversation') {
            setMeta((m) => ({ ...m, conversationId: event.id, title: event.title, provider: event.provider, model: event.model }))
          } else if (event.type === 'done') {
            setMeta((m) => ({ ...m, lastTraceId: event.trace_id, usage: event.usage }))
          }
          setItems((prev) => applyEvent(prev, event))
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          setItems((prev) => [...prev, { type: 'error', agent: 'copilot', depth: 0, message: (err as Error).message }])
        }
      } finally {
        setStreaming(false)
        qc.invalidateQueries({ queryKey: keys.conversations })
        qc.invalidateQueries({ queryKey: ['approvals'] })
        qc.invalidateQueries({ queryKey: ['traces'] })
      }
    },
    [meta.conversationId, streaming, qc],
  )

  const stop = useCallback(() => abort.current?.abort(), [])

  return { items, meta, streaming, loading, send, stop, load, setItems }
}
