import { Brain, ChevronRight, CircleCheck, CircleX, Clock, ShieldAlert, ShieldCheck, TriangleAlert, Wrench } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { AGENT_COLORS, MarkdownView } from '@/components/domain'
import { Badge, Button } from '@/components/ui'
import { keys, useAction, useApprovals } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { post } from '@/lib/api'
import type { Approval, ChatItem } from '@/lib/types'
import { cn, titleCase } from '@/lib/utils'

type ToolResult = Extract<ChatItem, { type: 'tool_result' }>

export function AgentChip({ agent, size = 'md' }: { agent: string; size?: 'sm' | 'md' }) {
  const color = AGENT_COLORS[agent] ?? '#6366f1'
  return (
    <span className={cn('inline-flex items-center gap-1.5 font-medium capitalize', size === 'sm' ? 'text-xs' : 'text-sm')}>
      <span className="grid size-5 place-items-center rounded-md text-[10px] font-bold text-white" style={{ background: color }}>
        {agent[0]?.toUpperCase()}
      </span>
      {agent}
    </span>
  )
}

/** Render one assistant turn (everything between two user messages). */
export function TurnView({ items, streaming }: { items: ChatItem[]; streaming: boolean }) {
  const results = new Map<string, ToolResult>()
  items.forEach((i) => i.type === 'tool_result' && results.set(i.id, i))
  const top = items.find((i) => i.type === 'agent_start' && i.depth === 0)

  const nodes: ReactNode[] = []
  for (let idx = 0; idx < items.length; idx++) {
    const item = items[idx]
    if (item.type === 'agent_start' && item.depth > 0) {
      // Collect the specialist's nested run.
      const inner: ChatItem[] = []
      let j = idx + 1
      for (; j < items.length; j++) {
        const it = items[j]
        if (it.type === 'agent_end' && it.depth === item.depth) break
        inner.push(it)
      }
      nodes.push(<DelegationCard key={idx} agent={item.agent} items={inner} results={results} done={j < items.length} />)
      idx = j
      continue
    }
    nodes.push(<ItemView key={idx} item={item} results={results} />)
  }

  return (
    <div className="flex gap-3 animate-fade-in">
      <div className="mt-0.5 shrink-0">
        <span className="grid size-8 place-items-center rounded-lg text-sm font-bold text-white" style={{ background: AGENT_COLORS[top?.type === 'agent_start' ? top.agent : 'copilot'] }}>
          {(top?.type === 'agent_start' ? top.agent : 'c')[0].toUpperCase()}
        </span>
      </div>
      <div className="min-w-0 flex-1 space-y-2.5">
        {top?.type === 'agent_start' && (
          <div className="flex items-center gap-2 text-xs text-muted">
            <span className="font-medium text-fg capitalize">{top.agent}</span>
            <Badge tone="neutral">{top.provider}{top.model ? ` · ${top.model}` : ''}</Badge>
          </div>
        )}
        {nodes}
        {streaming && <ThinkingDots />}
      </div>
    </div>
  )
}

function ItemView({ item, results }: { item: ChatItem; results: Map<string, ToolResult> }) {
  switch (item.type) {
    case 'text':
      return <MarkdownView>{item.text}</MarkdownView>
    case 'thinking':
      return <Reasoning text={item.text} />
    case 'tool_call':
      return item.name === 'delegate' ? null : <ToolCard call={item} result={results.get(item.id)} />
    case 'hook':
      return item.action === 'require_approval' ? null : (
        <div className="flex items-center gap-1.5 text-xs text-muted">
          <ShieldAlert className="size-3.5 text-[#b07800] dark:text-warning" />
          Hook <code className="font-mono">{item.hook}</code> → {item.action}
          {item.message && <span className="text-subtle">· {item.message}</span>}
        </div>
      )
    case 'approval':
    case 'approval_resolved':
      return <ApprovalCard approval={item.approval} />
    case 'error':
      return (
        <div className="rounded-lg border border-critical/30 bg-critical/5 px-3 py-2 text-sm">
          <div className="flex items-center gap-2 font-medium text-critical">
            <TriangleAlert className="size-4" /> {item.message}
          </div>
          {item.hint && <div className="mt-1 text-xs text-muted">{item.hint}</div>}
        </div>
      )
    default:
      return null
  }
}

function DelegationCard({ agent, items, results, done }: { agent: string; items: ChatItem[]; results: Map<string, ToolResult>; done: boolean }) {
  const color = AGENT_COLORS[agent] ?? '#6366f1'
  return (
    <div className="rounded-xl border border-border bg-surface-2/40" style={{ borderLeft: `3px solid ${color}` }}>
      <div className="flex items-center gap-2 px-3 pt-2.5 text-xs text-muted">
        <span>Delegated to</span>
        <AgentChip agent={agent} size="sm" />
        {!done && <ThinkingDots small />}
      </div>
      <div className="space-y-2.5 px-3 pt-1.5 pb-3">
        {items.map((it, i) => (
          <ItemView key={i} item={it} results={results} />
        ))}
      </div>
    </div>
  )
}

function Reasoning({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="text-xs">
      <button onClick={() => setOpen(!open)} className="inline-flex items-center gap-1 text-muted hover:text-fg">
        <Brain className="size-3.5" />
        Reasoning
        <ChevronRight className={cn('size-3.5 transition', open && 'rotate-90')} />
      </button>
      {open && <p className="mt-1.5 border-l-2 border-border pl-3 whitespace-pre-wrap text-muted">{text}</p>}
    </div>
  )
}

function ToolCard({ call, result }: { call: Extract<ChatItem, { type: 'tool_call' }>; result?: ToolResult }) {
  const [open, setOpen] = useState(false)
  const pending = (result?.result as { status?: string } | undefined)?.status === 'pending_approval'
  const icon = !result ? <Clock className="size-3.5 animate-pulse text-muted" /> : pending ? <ShieldAlert className="size-3.5 text-[#b07800] dark:text-warning" /> : result.ok ? <CircleCheck className="size-3.5 text-good" /> : <CircleX className="size-3.5 text-critical" />
  const argSummary = Object.entries(call.args)
    .slice(0, 3)
    .map(([k, v]) => `${k}=${typeof v === 'object' ? '…' : String(v)}`)
    .join(', ')
  return (
    <div className="rounded-lg border border-border bg-surface text-xs">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-3 py-2 text-left">
        {icon}
        <Wrench className="size-3.5 text-subtle" />
        <code className="font-mono font-medium text-fg">{call.name}</code>
        <span className="truncate text-subtle">{argSummary}</span>
        <span className="ml-auto flex shrink-0 items-center gap-2 text-subtle">
          {result && `${result.duration_ms}ms`}
          <ChevronRight className={cn('size-3.5 transition', open && 'rotate-90')} />
        </span>
      </button>
      {open && (
        <div className="grid gap-2 border-t border-border p-3 md:grid-cols-2">
          <div>
            <div className="mb-1 text-[11px] font-medium text-muted">Arguments</div>
            <pre className="max-h-48 overflow-auto rounded bg-surface-2 p-2 font-mono text-[11px]">{JSON.stringify(call.args, null, 2)}</pre>
          </div>
          <div>
            <div className="mb-1 text-[11px] font-medium text-muted">Result</div>
            <pre className="max-h-48 overflow-auto rounded bg-surface-2 p-2 font-mono text-[11px]">{result ? JSON.stringify(result.result, null, 2) : 'running…'}</pre>
          </div>
        </div>
      )}
    </div>
  )
}

export function ApprovalCard({ approval: initial }: { approval: Approval }) {
  const { can } = useAuth()
  const all = useApprovals('all')
  const approval = all.data?.find((a) => a.id === initial.id) ?? initial
  const decide = useAction((approve: boolean) => post<Approval>(`/api/agents/approvals/${approval.id}`, { approve }), {
    success: (a) => `Approval #${a.id} ${a.status}`,
    invalidate: [['approvals'], keys.products, keys.dashboard, ['purchase-orders']],
  })
  const tone = approval.status === 'approved' ? 'good' : approval.status === 'pending' ? 'warning' : 'critical'
  return (
    <div className={cn('rounded-xl border p-3 text-sm', approval.status === 'pending' ? 'border-warning/50 bg-warning/5' : 'border-border bg-surface')}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 font-medium">
          <ShieldCheck className="size-4 text-brand" />
          Approval #{approval.id} · {titleCase(approval.tool)}
        </div>
        <Badge tone={tone} className="capitalize">{approval.status}</Badge>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {Object.entries(approval.args).map(([k, v]) => (
          <span key={k} className="rounded-md bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-muted">
            {k}: <span className="text-fg">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
          </span>
        ))}
      </div>
      {approval.reason && <p className="mt-2 text-xs text-muted">{approval.reason}</p>}
      {approval.status === 'pending' && can('manager') && (
        <div className="mt-3 flex gap-2">
          <Button size="sm" variant="success" onClick={() => decide.mutate(true)} loading={decide.isPending && decide.variables === true}>
            Approve & run
          </Button>
          <Button size="sm" variant="secondary" onClick={() => decide.mutate(false)} loading={decide.isPending && decide.variables === false}>
            Reject
          </Button>
        </div>
      )}
      {approval.status === 'pending' && !can('manager') && <p className="mt-2 text-xs text-subtle">Waiting for a manager to approve.</p>}
      {approval.result && approval.status !== 'pending' && (
        <pre className="mt-2 max-h-32 overflow-auto rounded bg-surface-2 p-2 font-mono text-[11px] text-muted">{JSON.stringify(approval.result, null, 2)}</pre>
      )}
    </div>
  )
}

function ThinkingDots({ small }: { small?: boolean }) {
  return (
    <span className={cn('inline-flex items-center gap-1', small ? '' : 'py-1')} aria-label="Working">
      {[0, 1, 2].map((i) => (
        <span key={i} className="size-1.5 rounded-full bg-brand animate-pulse-dot" style={{ animationDelay: `${i * 0.2}s` }} />
      ))}
    </span>
  )
}
