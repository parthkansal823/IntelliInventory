import { Mic, MicOff, Plus, SendHorizontal, Square, Trash2, Volume2, VolumeX } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useSearchParams } from 'react-router'
import { AgentChip, ApprovalCard, TurnView } from '@/components/copilot/ChatView'
import { TracePanel } from '@/components/copilot/TracePanel'
import { AGENT_COLORS } from '@/components/domain'
import { Badge, Card, EmptyState, Segmented, Select, Tabs, TabsContent, TabsList, TabsTrigger, Tooltip } from '@/components/ui'
import { keys, useAction, useAgents, useApprovals, useConversations } from '@/hooks/queries'
import { useAgentChat } from '@/hooks/useAgentChat'
import { del } from '@/lib/api'
import { canSpeak, createRecognition, speak, stopSpeaking, voiceLang, type VoiceLang } from '@/lib/speech'
import type { ChatItem } from '@/lib/types'
import { cn, relativeTime } from '@/lib/utils'

const SUGGESTIONS = [
  { title: 'Aaj ki sale', prompt: 'aaj ki sale kitni hui?' },
  { title: 'Udhaar', prompt: 'kiska udhaar baaki hai?' },
  { title: 'Diwali stock', prompt: 'Diwali ke liye kya stock karna hai?' },
  { title: 'What to reorder', prompt: 'kaunsa stock kam hai aur kya order karna hai?' },
  { title: 'GST this month', prompt: 'is mahine GST kitna banega?' },
  { title: 'Morning briefing', prompt: 'Give me this morning’s inventory briefing' },
  { title: 'What-if', prompt: 'What if demand for ATA-105 (sugar) rises 30% and lead time becomes 7 days?' },
  { title: 'Investigate', prompt: 'Any anomalies or suspicious write-offs this week?' },
]

function groupTurns(items: ChatItem[]) {
  const turns: { user?: Extract<ChatItem, { type: 'user' }>; items: ChatItem[] }[] = []
  for (const item of items) {
    if (item.type === 'user') turns.push({ user: item, items: [] })
    else if (!turns.length) turns.push({ items: [item] })
    else turns[turns.length - 1].items.push(item)
  }
  return turns
}

export default function Copilot() {
  const [params, setParams] = useSearchParams()
  const overview = useAgents()
  const conversations = useConversations()
  const approvals = useApprovals()
  const [agent, setAgent] = useState('copilot')
  const [provider, setProvider] = useState('auto')
  const [input, setInput] = useState('')
  const [readAloud, setReadAloud] = useState(false)
  const [listening, setListening] = useState(false)
  const conversationId = params.get('c')
  const chat = useAgentChat(conversationId)
  const scroller = useRef<HTMLDivElement>(null)
  const autoSent = useRef<string | null>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const recognition = useRef<ReturnType<typeof createRecognition>>(null)
  const [lang, setLang] = useState<VoiceLang>(voiceLang.get)
  const switchLang = () => {
    const next = lang === 'hi-IN' ? 'en-IN' : 'hi-IN'
    voiceLang.set(next)
    setLang(next)
  }

  const turns = useMemo(() => groupTurns(chat.items), [chat.items])
  const removeConv = useAction((id: string) => del(`/api/agents/conversations/${id}`), { invalidate: [keys.conversations] })

  // Keep the URL in sync with the active conversation (enables deep links / history).
  useEffect(() => {
    if (chat.meta.conversationId && chat.meta.conversationId !== conversationId) {
      setParams({ c: chat.meta.conversationId }, { replace: true })
    }
  }, [chat.meta.conversationId, conversationId, setParams])

  // ?q= from the command palette / dashboard: send once.
  useEffect(() => {
    const q = params.get('q')
    if (q && autoSent.current !== q && !chat.loading) {
      autoSent.current = q
      setParams({}, { replace: true })
      chat.send(q, { agent, provider })
    }
  }, [params, chat, agent, provider, setParams])

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }, [chat.items])

  // Read the final answer aloud when a run completes.
  const wasStreaming = useRef(false)
  useEffect(() => {
    if (wasStreaming.current && !chat.streaming && readAloud) {
      const last = [...chat.items].reverse().find((i) => i.type === 'agent_end' && i.depth === 0)
      if (last?.type === 'agent_end') speak(last.text, undefined, lang)
    }
    wasStreaming.current = chat.streaming
  }, [chat.streaming, chat.items, readAloud, lang])

  const send = (text = input) => {
    if (!text.trim()) return
    chat.send(text.trim(), { agent, provider })
    setInput('')
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }
  const toggleMic = () => {
    if (listening) {
      recognition.current?.stop()
      return
    }
    const rec = createRecognition(lang)
    if (!rec) return
    recognition.current = rec
    rec.onresult = (e) => {
      const transcript = Array.from(e.results).map((r) => r[0].transcript).join('')
      setInput(transcript)
      if (e.results[e.results.length - 1].isFinal) send(transcript)
    }
    rec.onend = () => setListening(false)
    rec.onerror = () => setListening(false)
    rec.start()
    setListening(true)
  }

  const providers = overview.data?.providers ?? []
  const active = overview.data?.active_provider
  const agents = overview.data?.agents ?? []
  const agentInfo = agents.find((a) => a.name === agent)

  return (
    <div className="-my-6 grid h-[calc(100vh-3.5rem)] grid-cols-[minmax(0,1fr)] gap-0 lg:-mx-6 lg:grid-cols-[15rem_minmax(0,1fr)] xl:grid-cols-[15rem_minmax(0,1fr)_20rem]">
      {/* Conversations */}
      <aside className="hidden flex-col border-r border-border lg:flex">
        <div className="p-3">
          <button onClick={() => { chat.load(null); setParams({}) }} className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-border py-2 text-sm text-muted transition hover:border-brand hover:text-brand">
            <Plus className="size-4" /> New chat
          </button>
        </div>
        <ul className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
          {conversations.data?.map((c) => (
            <li key={c.id} className="group relative">
              <button
                onClick={() => setParams({ c: c.id })}
                className={cn('w-full rounded-lg px-3 py-2 text-left transition', c.id === chat.meta.conversationId ? 'bg-brand-soft' : 'hover:bg-surface-2')}
              >
                <div className="truncate pr-5 text-sm">{c.title}</div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-subtle">
                  <span className="size-1.5 rounded-full" style={{ background: AGENT_COLORS[c.agent] }} />
                  {c.agent} · {relativeTime(c.updated_at)}
                </div>
              </button>
              <button onClick={() => removeConv.mutate(c.id)} className="absolute top-2 right-2 hidden rounded p-1 text-subtle hover:text-critical group-hover:block" aria-label="Delete conversation">
                <Trash2 className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {/* Chat */}
      <section className="flex min-h-0 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
          <Segmented
            size="sm"
            value={agent}
            onChange={setAgent}
            options={(agents.length ? agents : [{ name: 'copilot', title: 'Copilot' }]).map((a) => ({
              value: a.name,
              label: (
                <span className="flex items-center gap-1.5">
                  <span className="hidden size-2 rounded-full 2xl:inline-block" style={{ background: AGENT_COLORS[a.name] }} />
                  {a.title}
                </span>
              ),
            }))}
          />
          <div className="ml-auto flex items-center gap-2">
            <Select value={provider} onChange={(e) => setProvider(e.target.value)} className="h-8 w-40 text-xs" aria-label="AI provider">
              <option value="auto">Auto ({active ?? '…'})</option>
              {providers.map((p) => (
                <option key={p.name} value={p.name} disabled={!p.configured}>
                  {p.label}
                  {p.model ? ` · ${p.model}` : ''}
                  {p.free ? ' · free' : ''}
                  {!p.configured ? ' (not set up)' : ''}
                </option>
              ))}
            </Select>
            {canSpeak() && (
              <Tooltip content={readAloud ? 'Stop reading answers aloud' : 'Read answers aloud'}>
                <button onClick={() => { setReadAloud(!readAloud); stopSpeaking() }} className={cn('rounded-lg p-2', readAloud ? 'bg-brand-soft text-brand' : 'text-muted hover:bg-surface-2')} aria-label="Read aloud">
                  {readAloud ? <Volume2 className="size-4" /> : <VolumeX className="size-4" />}
                </button>
              </Tooltip>
            )}
          </div>
        </div>

        <div ref={scroller} className="flex-1 overflow-y-auto px-4 py-6">
          <div className="mx-auto max-w-3xl space-y-6">
            {!turns.length && !chat.loading && (
              <div className="pt-6 text-center">
                <div className="mx-auto grid size-12 place-items-center rounded-2xl text-xl font-bold text-white" style={{ background: AGENT_COLORS[agent] }}>
                  {agent[0].toUpperCase()}
                </div>
                <h2 className="mt-4 text-lg font-semibold">{agentInfo?.title ?? 'Copilot'}</h2>
                <p className="mx-auto mt-1 max-w-md text-sm text-muted">{agentInfo?.description}</p>
                <div className="mt-2 flex justify-center gap-1.5">
                  {providers.filter((p) => p.name === active).map((p) => (
                    <Badge key={p.name} tone={p.free ? 'good' : 'brand'}>
                      {p.label}{p.model ? ` · ${p.model}` : ''}{p.free ? ' · free' : ''}
                    </Badge>
                  ))}
                </div>
                <div className="mt-8 grid gap-2 text-left sm:grid-cols-2">
                  {SUGGESTIONS.map((s) => (
                    <button key={s.title} onClick={() => send(s.prompt)} className="rounded-xl border border-border bg-surface p-3 text-left transition hover:border-brand/50 hover:shadow-sm">
                      <div className="text-xs font-medium text-brand">{s.title}</div>
                      <div className="mt-0.5 text-sm text-muted">{s.prompt}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}
            {turns.map((turn, i) => (
              <div key={i} className="space-y-4">
                {turn.user && (
                  <div className="flex justify-end">
                    <div className="max-w-[85%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-sm whitespace-pre-wrap text-brand-fg shadow-sm">{turn.user.text}</div>
                  </div>
                )}
                {(turn.items.length > 0 || (chat.streaming && i === turns.length - 1)) && (
                  <TurnView items={turn.items} streaming={chat.streaming && i === turns.length - 1} />
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="border-t border-border bg-bg p-3">
          <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-border bg-surface p-2 shadow-sm focus-within:border-brand/50">
            <textarea
              ref={textarea}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKey}
              rows={1}
              placeholder={listening ? 'Listening…' : `Message ${agentInfo?.title ?? 'Copilot'} — Enter to send, Shift+Enter for a new line`}
              className="max-h-40 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-subtle"
            />
            {createRecognitionSupported() && (
              <Tooltip content={lang === 'hi-IN' ? 'Voice: Hindi — click for English' : 'Voice: English — click for Hindi'}>
                <button onClick={switchLang} className="rounded-xl px-2 py-1.5 text-xs font-semibold text-muted hover:bg-surface-2" aria-label="Voice language">
                  {lang === 'hi-IN' ? 'हिं' : 'EN'}
                </button>
              </Tooltip>
            )}
            {createRecognitionSupported() && (
              <Tooltip content={listening ? 'Stop listening' : lang === 'hi-IN' ? 'बोलिए (Hindi / Hinglish)' : 'Speak (English / Hinglish)'}>
                <button onClick={toggleMic} className={cn('rounded-xl p-2', listening ? 'bg-critical/10 text-critical' : 'text-muted hover:bg-surface-2')} aria-label="Voice input">
                  {listening ? <MicOff className="size-4" /> : <Mic className="size-4" />}
                </button>
              </Tooltip>
            )}
            {chat.streaming ? (
              <button onClick={chat.stop} className="rounded-xl bg-fg p-2 text-bg" aria-label="Stop">
                <Square className="size-4" />
              </button>
            ) : (
              <button onClick={() => send()} disabled={!input.trim()} className="rounded-xl bg-brand p-2 text-brand-fg disabled:opacity-40" aria-label="Send">
                <SendHorizontal className="size-4" />
              </button>
            )}
          </div>
          <p className="mx-auto mt-1.5 max-w-3xl text-center text-[11px] text-subtle">
            Agents use live tools. Stock changes, transfers and PO status changes always wait for a manager's approval.
          </p>
        </div>
      </section>

      {/* Right rail: approvals + trace */}
      <aside className="hidden min-h-0 flex-col border-l border-border xl:flex">
        <Tabs defaultValue="approvals" className="flex min-h-0 flex-1 flex-col">
          <TabsList className="px-3 pt-2">
            <TabsTrigger value="approvals">
              Approvals {approvals.data?.length ? <Badge tone="warning">{approvals.data.length}</Badge> : null}
            </TabsTrigger>
            <TabsTrigger value="trace">Trace</TabsTrigger>
            <TabsTrigger value="agents">Agents</TabsTrigger>
          </TabsList>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            <TabsContent value="approvals" className="space-y-3 pt-1">
              {approvals.data?.length ? approvals.data.map((a) => <ApprovalCard key={a.id} approval={a} />) : <EmptyState title="Nothing to approve" description="Write actions requested by agents appear here." />}
            </TabsContent>
            <TabsContent value="trace" className="pt-1">
              <TracePanel conversationId={chat.meta.conversationId} />
            </TabsContent>
            <TabsContent value="agents" className="space-y-2 pt-1">
              {agents.map((a) => (
                <Card key={a.name} className="p-3">
                  <AgentChip agent={a.name} />
                  <p className="mt-1 text-xs text-muted">{a.description}</p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {a.tools.map((t) => (
                      <code key={t} className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-muted">{t}</code>
                    ))}
                  </div>
                </Card>
              ))}
            </TabsContent>
          </div>
        </Tabs>
      </aside>
    </div>
  )
}

function createRecognitionSupported() {
  return typeof window !== 'undefined' && ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)
}
