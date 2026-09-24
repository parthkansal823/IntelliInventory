import { Brain, GitBranch, ShieldAlert, ShieldCheck, Wrench } from 'lucide-react'
import { useState } from 'react'
import { AGENT_COLORS } from '@/components/domain'
import { Badge, EmptyState, Skeleton } from '@/components/ui'
import { useTrace, useTraces } from '@/hooks/queries'
import type { TraceStep } from '@/lib/types'
import { cn, relativeTime } from '@/lib/utils'

const ICONS = { llm: Brain, tool: Wrench, hook: ShieldAlert, approval: ShieldCheck, delegate: GitBranch } as const

function stepLabel(s: TraceStep): string {
  switch (s.kind) {
    case 'llm':
      return `LLM step ${Number(s.step) + 1}${Array.isArray(s.tool_calls) && s.tool_calls.length ? ` → ${(s.tool_calls as string[]).join(', ')}` : ' → answer'}`
    case 'tool':
      return `${s.name}${s.decision && s.decision !== 'allow' ? ` (${s.decision})` : ''}`
    case 'hook':
      return `${s.hook}: ${s.action}`
    case 'approval':
      return `approval #${s.approval_id} for ${s.tool}`
    case 'delegate':
      return `delegate → ${s.to}`
  }
}

/** Timeline of one agent run: LLM turns, hook decisions, tool calls, delegations. */
export function TracePanel({ conversationId }: { conversationId: string | null }) {
  const traces = useTraces(conversationId ?? undefined)
  const [selected, setSelected] = useState<string | null>(null)
  const id = selected ?? traces.data?.[0]?.id ?? null
  const trace = useTrace(id)

  if (!conversationId) return <EmptyState title="No run yet" description="Send a message to see the agent's step-by-step trace." />
  if (traces.isLoading) return <Skeleton className="h-40" />
  if (!traces.data?.length) return <EmptyState title="No traces yet" />

  const t = trace.data
  const total = Math.max(t?.duration_ms ?? 1, 1)
  return (
    <div className="space-y-3">
      <select value={id ?? ''} onChange={(e) => setSelected(e.target.value)} className="w-full rounded-lg border border-border bg-surface px-2 py-1.5 text-xs">
        {traces.data.map((tr) => (
          <option key={tr.id} value={tr.id}>
            {relativeTime(tr.created_at)} · {tr.input.slice(0, 40)}
          </option>
        ))}
      </select>
      {t && (
        <>
          <div className="grid grid-cols-3 gap-2 text-center">
            {[
              ['Duration', `${(t.duration_ms / 1000).toFixed(2)}s`],
              ['Tokens', `${t.input_tokens + t.output_tokens}`],
              ['Provider', t.provider],
            ].map(([k, v]) => (
              <div key={k} className="rounded-lg bg-surface-2 px-2 py-1.5">
                <div className="text-[10px] text-muted">{k}</div>
                <div className="truncate text-xs font-medium">{v}</div>
              </div>
            ))}
          </div>
          <ol className="relative space-y-1 border-l border-border pl-4">
            {t.steps.map((s, i) => {
              const Icon = ICONS[s.kind] ?? Wrench
              const dur = Number(s.duration_ms ?? 0)
              return (
                <li key={i} className="relative py-1">
                  <span className="absolute top-2 -left-[21px] grid size-2.5 place-items-center rounded-full border-2 border-surface" style={{ background: AGENT_COLORS[s.agent] ?? '#6366f1' }} />
                  <div className="flex items-center gap-1.5 text-xs">
                    <Icon className="size-3.5 shrink-0 text-muted" />
                    <span className="truncate font-medium">{stepLabel(s)}</span>
                    {s.ok === false && <Badge tone="critical">error</Badge>}
                    <span className="ml-auto shrink-0 text-[10px] text-subtle tabular-nums">+{s.at_ms}ms</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 pl-5 text-[10px] text-subtle">
                    <span className="capitalize">{s.agent}</span>
                    {dur > 0 && (
                      <>
                        <span className="h-1 flex-1 overflow-hidden rounded bg-surface-2">
                          <span className={cn('block h-full rounded', s.kind === 'llm' ? 'bg-[var(--chart-1)]' : 'bg-[var(--chart-3)]')} style={{ width: `${Math.max(3, (dur / total) * 100)}%` }} />
                        </span>
                        <span className="tabular-nums">{dur}ms</span>
                      </>
                    )}
                    {typeof s.output_tokens === 'number' && s.output_tokens > 0 && <span>{String(s.output_tokens)} tok</span>}
                  </div>
                </li>
              )
            })}
          </ol>
        </>
      )}
    </div>
  )
}
