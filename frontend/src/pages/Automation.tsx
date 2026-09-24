import { Bot, CalendarClock, Plug, Play, Plus, Radio, Send, ShieldCheck, Trash2, Webhook as WebhookIcon, Zap } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Actor } from '@/components/domain'
import { Badge, Button, Card, CardHeader, CodeBlock, Dialog, EmptyState, Field, Input, PageHeader, Skeleton, Switch, Tooltip } from '@/components/ui'
import { keys, useAction, useAutomationSettings, useHooks, useJobs, useWebhooks } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { useLiveEvents } from '@/hooks/useLiveEvents'
import { del, get, patch, post } from '@/lib/api'
import type { HookInfo, LiveEvent, Webhook } from '@/lib/types'
import { relativeTime, timeOnly } from '@/lib/utils'
import { useQuery } from '@tanstack/react-query'

const LIFECYCLE = ['pre_llm_call', 'pre_tool_call', 'post_tool_call', 'post_llm_call', 'agent:start', 'agent:step', 'agent:end']

export default function Automation() {
  return (
    <div className="space-y-6">
      <PageHeader title="Automation" description="Agent lifecycle hooks, event hooks, autopilot, scheduled jobs, webhooks and the live audit trail." />
      <div className="grid gap-4 lg:grid-cols-3">
        <AutopilotCard />
        <JobsCard />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <AgentHooksCard />
        <EventHooksCard />
      </div>
      <WebhooksCard />
      <EventLogCard />
    </div>
  )
}

function useToggle() {
  return useAction(({ name, enabled }: { name: string; enabled: boolean }) => patch(`/api/hooks/${encodeURIComponent(name)}`, { enabled }), {
    success: 'Hook updated',
    invalidate: [keys.hooks, keys.agents],
  })
}

function HookRow({ hook }: { hook: HookInfo }) {
  const { can } = useAuth()
  const toggle = useToggle()
  return (
    <li className="flex items-start justify-between gap-3 py-2.5">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-1.5">
          <code className="text-sm font-medium">{hook.name}</code>
          {!hook.builtin && <Badge tone="brand"><Plug className="size-3" /> plugin</Badge>}
          {hook.async && <Badge>async</Badge>}
          {hook.pattern && <Badge tone="info" className="font-mono">{hook.pattern}</Badge>}
        </div>
        <p className="mt-0.5 text-xs text-muted">{hook.description}</p>
      </div>
      <Switch checked={hook.enabled} disabled={!can('manager')} onCheckedChange={(enabled) => toggle.mutate({ name: hook.name, enabled })} label={`Toggle ${hook.name}`} />
    </li>
  )
}

function AgentHooksCard() {
  const hooks = useHooks()
  const grouped = useMemo(() => LIFECYCLE.map((ev) => ({ ev, list: hooks.data?.agent.filter((h) => h.event === ev) ?? [] })).filter((g) => g.list.length), [hooks.data])
  return (
    <Card>
      <CardHeader title="Agent lifecycle hooks" description="Same contract as Hermes Agent plugins: block · modify · require approval · inject context" icon={<ShieldCheck className="size-4" />} />
      <div className="px-5 pb-4">
        {!hooks.data ? <Skeleton className="h-48" /> : grouped.map((g) => (
          <div key={g.ev} className="mb-2">
            <div className="text-[11px] font-semibold tracking-wide text-subtle uppercase">{g.ev}</div>
            <ul className="divide-y divide-border">{g.list.map((h) => <HookRow key={h.name} hook={h} />)}</ul>
          </div>
        ))}
      </div>
    </Card>
  )
}

function EventHooksCard() {
  const hooks = useHooks()
  return (
    <Card>
      <CardHeader title="Event hooks" description="React to domain events (glob patterns) — sync or async, failures isolated" icon={<Zap className="size-4" />} />
      <div className="px-5 pb-4">
        {!hooks.data ? <Skeleton className="h-48" /> : <ul className="divide-y divide-border">{hooks.data.event.map((h) => <HookRow key={h.name} hook={h} />)}</ul>}
        {!!hooks.data?.plugins.length && (
          <div className="mt-4 rounded-lg border border-dashed border-border p-3">
            <div className="text-xs font-medium text-muted">Loaded plugins</div>
            {hooks.data.plugins.map((p) => (
              <div key={p.name} className="mt-1.5 text-sm">
                <code className="font-medium">{p.name}</code> <span className="text-xs text-muted">— {p.description}</span>
                <div className="mt-1 flex flex-wrap gap-1">{p.registered.map((r) => <Badge key={r}>{r}</Badge>)}</div>
              </div>
            ))}
            <p className="mt-2 text-xs text-subtle">Drop a <code>register(ctx)</code> module into <code>backend/app/plugins/</code> or <code>PLUGINS_DIR</code> to add hooks and tools.</p>
          </div>
        )}
      </div>
    </Card>
  )
}

function AutopilotCard() {
  const settings = useAutomationSettings()
  const { can } = useAuth()
  const update = useAction((enabled: boolean) => patch('/api/automation/settings', { autopilot_enabled: enabled }), {
    success: (r) => ((r as { autopilot_enabled: boolean }).autopilot_enabled ? 'Autopilot on' : 'Autopilot off'),
    invalidate: [keys.automation],
  })
  const on = settings.data?.autopilot_enabled ?? false
  return (
    <Card className="relative overflow-hidden">
      <div className="pointer-events-none absolute -top-12 -right-12 size-40 rounded-full bg-brand/10 blur-2xl" />
      <CardHeader
        title="Procurement autopilot"
        description="Event-driven agent: when stock drops below the reorder point, the Procurement agent drafts a PO for approval."
        icon={<Bot className="size-4" />}
        action={<Switch checked={on} disabled={!can('manager')} onCheckedChange={(v) => update.mutate(v)} label="Autopilot" />}
      />
      <div className="space-y-2 px-5 pb-5 text-sm text-muted">
        <div className="flex items-center gap-2"><Badge tone={on ? 'good' : 'neutral'}>{on ? 'Active' : 'Paused'}</Badge> cooldown {settings.data?.autopilot_cooldown_hours ?? 12}h per SKU</div>
        <ol className="list-decimal space-y-1 pl-5 text-xs">
          <li><code>stock.changed</code> → alert engine → <code>stock.low</code></li>
          <li>skips SKUs that already have an open PO</li>
          <li>agent drafts one PO per supplier → approval queue</li>
        </ol>
      </div>
    </Card>
  )
}

function JobsCard() {
  const jobs = useJobs()
  const { can } = useAuth()
  const run = useAction((name: string) => post<{ result: string }>(`/api/jobs/${name}/run`), { success: (r) => `Done: ${r.result}`, invalidate: [keys.jobs, keys.reports, keys.alerts] })
  return (
    <Card className="lg:col-span-2">
      <CardHeader title="Scheduled jobs" description="Built-in asyncio scheduler — no extra infrastructure" icon={<CalendarClock className="size-4" />} />
      <ul className="divide-y divide-border px-5 pb-3">
        {!jobs.data && <Skeleton className="h-32" />}
        {jobs.data?.map((j) => (
          <li key={j.name} className="flex items-center justify-between gap-4 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2"><code className="text-sm font-medium">{j.name}</code><Badge>every {j.interval_minutes >= 60 ? `${j.interval_minutes / 60}h` : `${j.interval_minutes}m`}</Badge></div>
              <p className="text-xs text-muted">{j.description}</p>
              <p className="text-xs text-subtle">Last run {relativeTime(j.last_run)}{j.last_result ? ` · ${j.last_result}` : ''}</p>
            </div>
            {can('manager') && <Button size="sm" variant="secondary" onClick={() => run.mutate(j.name)} loading={run.isPending && run.variables === j.name}><Play className="size-3.5" /> Run now</Button>}
          </li>
        ))}
      </ul>
    </Card>
  )
}

function WebhooksCard() {
  const hooks = useWebhooks()
  const { can } = useAuth()
  const [adding, setAdding] = useState(false)
  const [url, setUrl] = useState('')
  const [events, setEvents] = useState('stock.*, po.*, approval.requested, report.created')
  const [created, setCreated] = useState<Webhook | null>(null)
  const [openId, setOpenId] = useState<number | null>(null)
  const create = useAction(() => post<Webhook>('/api/webhooks', { url, events: events.split(',').map((e) => e.trim()).filter(Boolean) }), {
    success: 'Webhook created', invalidate: [keys.webhooks], onSuccess: (w) => { setCreated(w); setAdding(false); setUrl('') },
  })
  const remove = useAction((id: number) => del(`/api/webhooks/${id}`), { success: 'Webhook deleted', invalidate: [keys.webhooks] })
  const test = useAction((id: number) => post<{ success: boolean; status_code: number | null; error: string | null }>(`/api/webhooks/${id}/test`), {
    success: (r) => (r.success ? `Delivered (HTTP ${r.status_code})` : `Failed: ${r.error}`), invalidate: [keys.webhooks],
  })
  const deliveries = useQuery({ queryKey: ['deliveries', openId], queryFn: () => get<{ id: number; event_type: string; status_code: number | null; success: boolean; attempts: number; duration_ms: number; created_at: string; error: string | null }[]>(`/api/webhooks/${openId}/deliveries`), enabled: !!openId })

  return (
    <Card>
      <CardHeader
        title="Webhooks"
        description="HMAC-SHA256 signed (X-IntelliInventory-Signature), 3 retries with backoff. Slack & Discord URLs get chat-formatted messages."
        icon={<WebhookIcon className="size-4" />}
        action={can('admin') && <Button size="sm" onClick={() => setAdding(true)}><Plus className="size-3.5" /> Add webhook</Button>}
      />
      <div className="px-5 pb-5">
        {!hooks.data?.length ? (
          <EmptyState title="No webhooks yet" description="Send stock alerts, PO updates and AI briefings to Slack, Discord, Zapier, n8n or your own service." />
        ) : (
          <ul className="divide-y divide-border">
            {hooks.data.map((w) => (
              <li key={w.id} className="py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate font-mono text-sm">{w.url}</div>
                    <div className="mt-1 flex flex-wrap gap-1">{w.events.map((e) => <Badge key={e} tone="info" className="font-mono">{e}</Badge>)}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    {w.last_status != null && <Badge tone={w.last_status < 300 ? 'good' : 'critical'}>HTTP {w.last_status}</Badge>}
                    {w.last_error && <Tooltip content={w.last_error}><Badge tone="critical">error</Badge></Tooltip>}
                    <Button size="sm" variant="ghost" onClick={() => setOpenId(openId === w.id ? null : w.id)}>Deliveries</Button>
                    <Button size="sm" variant="secondary" onClick={() => test.mutate(w.id)} loading={test.isPending && test.variables === w.id}><Send className="size-3.5" /> Test</Button>
                    {can('admin') && <Button size="icon" variant="ghost" onClick={() => remove.mutate(w.id)} aria-label="Delete webhook"><Trash2 className="size-4" /></Button>}
                  </div>
                </div>
                {openId === w.id && (
                  <ul className="mt-2 max-h-48 overflow-y-auto rounded-lg bg-surface-2 p-2 text-xs">
                    {deliveries.data?.length ? deliveries.data.map((d) => (
                      <li key={d.id} className="flex justify-between gap-2 py-1">
                        <span className="font-mono">{d.event_type}</span>
                        <span className={d.success ? 'text-good' : 'text-critical'}>{d.status_code ?? d.error} · {d.attempts}× · {d.duration_ms}ms · {relativeTime(d.created_at)}</span>
                      </li>
                    )) : <li className="text-muted">No deliveries yet.</li>}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      <Dialog open={adding} onOpenChange={setAdding} title="Add webhook" footer={<Button onClick={() => create.mutate(undefined)} loading={create.isPending} disabled={!url}>Create</Button>}>
        <div className="space-y-4">
          <Field label="Endpoint URL" hint="Slack / Discord incoming-webhook URLs are auto-formatted"><Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://hooks.slack.com/services/…" /></Field>
          <Field label="Events (comma-separated globs)" hint="e.g. * for everything"><Input value={events} onChange={(e) => setEvents(e.target.value)} /></Field>
        </div>
      </Dialog>
      <Dialog open={!!created} onOpenChange={(o) => !o && setCreated(null)} title="Signing secret" description="Shown once — use it to verify the X-IntelliInventory-Signature header.">
        {created?.secret && <CodeBlock code={created.secret} />}
        <CodeBlock code={`# Python verification\nimport hmac, hashlib\nexpected = "sha256=" + hmac.new(SECRET.encode(), request_body, hashlib.sha256).hexdigest()\nassert hmac.compare_digest(expected, request.headers["X-IntelliInventory-Signature"])`} />
      </Dialog>
    </Card>
  )
}

function EventLogCard() {
  const { events: live, connected } = useLiveEvents()
  const history = useQuery({ queryKey: keys.events, queryFn: () => get<{ id: number; type: string; source: string; payload: Record<string, unknown>; ts: string }[]>('/api/events?limit=80') })
  const [filter, setFilter] = useState('')
  const merged: LiveEvent[] = useMemo(() => {
    const seen = new Set<string>()
    const rows = [...live, ...(history.data ?? []).map((e) => ({ id: String(e.id), type: e.type, payload: e.payload, source: e.source, ts: e.ts }))]
    return rows.filter((e) => {
      const key = `${e.type}|${e.ts.slice(0, 19)}`
      if (seen.has(key)) return false
      seen.add(key)
      return !filter || e.type.includes(filter)
    })
  }, [live, history.data, filter])

  return (
    <Card>
      <CardHeader
        title="Audit trail"
        description="Every domain event, persisted by the audit_log hook and streamed live over SSE"
        icon={<Radio className="size-4" />}
        action={
          <div className="flex items-center gap-2">
            <Badge tone={connected ? 'good' : 'neutral'}>{connected ? 'live' : 'offline'}</Badge>
            <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter e.g. stock." className="h-8 w-44" />
          </div>
        }
      />
      <div className="max-h-[28rem] overflow-y-auto px-5 pb-5">
        <table className="w-full text-xs">
          <tbody>
            {merged.slice(0, 150).map((e) => (
              <tr key={`${e.id}-${e.ts}`} className="border-b border-border/60 align-top">
                <td className="py-1.5 pr-3 whitespace-nowrap text-subtle">{timeOnly(e.ts)}</td>
                <td className="py-1.5 pr-3"><code className="font-medium">{e.type}</code></td>
                <td className="py-1.5 pr-3"><Actor actor={e.source} /></td>
                <td className="max-w-md truncate py-1.5 font-mono text-muted">{JSON.stringify(e.payload)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
