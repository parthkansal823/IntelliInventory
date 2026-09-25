import {
  Activity,
  Bot,
  Boxes,
  ChevronRight,
  Gauge,
  IndianRupee,
  PackageX,
  Radar,
  Receipt,
  RefreshCw,
  ShoppingCart,
  Sparkles,
  TrendingUp,
  TriangleAlert,
  Volume2,
  VolumeX,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { BarList, SalesTrendChart, StockHealth } from '@/components/charts'
import { Actor, Kpi, MarkdownView, SeverityIcon, StatusBadge } from '@/components/domain'
import { NextFestivalCard } from '@/components/india'
import { Badge, Button, Card, CardHeader, EmptyState, Skeleton } from '@/components/ui'
import { keys, useAction, useAlerts, useBillingSummary, useDashboard, useHealth, useProducts, useReorder, useReports } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { useLiveEvents } from '@/hooks/useLiveEvents'
import { post } from '@/lib/api'
import { canSpeak, speak, stopSpeaking } from '@/lib/speech'
import type { ProductRow } from '@/lib/types'
import { cn, greeting, IST, money, moneyCompact, number, relativeTime, titleCase } from '@/lib/utils'

export default function Dashboard() {
  const { user, can } = useAuth()
  const navigate = useNavigate()
  const dash = useDashboard()
  const k = dash.data?.kpis

  const draftAll = useAction(() => post<unknown[]>('/api/purchase-orders/from-recommendations', {}), {
    success: (r) => `Drafted ${r.length} purchase order${r.length === 1 ? '' : 's'} — one per supplier`,
    invalidate: [['purchase-orders'], keys.dashboard, keys.reorder],
    onSuccess: () => navigate('/purchase-orders'),
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {greeting()}, {user?.name.split(' ')[0]} 👋
          </h1>
          <p className="mt-1 text-sm text-muted">
            {new Date().toLocaleDateString('en-IN', { weekday: 'long', month: 'long', day: 'numeric', timeZone: IST })} · here's what needs your attention.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => navigate('/copilot?q=What%20should%20I%20reorder%20today%3F')}>
            <Sparkles className="size-4" /> Ask Copilot
          </Button>
          {can('staff') && (
            <Button onClick={() => draftAll.mutate(undefined)} loading={draftAll.isPending} disabled={!k?.reorder_needed}>
              <ShoppingCart className="size-4" /> Draft reorder POs{k?.reorder_needed ? ` (${k.reorder_needed})` : ''}
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <TodayBillingCard />
        <NextFestivalCard />
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Inventory value" value={moneyCompact(k?.inventory_value)} icon={<IndianRupee className="size-4" />} hint={`${number(k?.total_units)} units`} loading={dash.isLoading} />
        <Kpi label="Revenue · 30d" value={moneyCompact(k?.revenue_30d)} icon={<TrendingUp className="size-4" />} delta={k?.revenue_change_pct} hint="vs prior 30d" loading={dash.isLoading} />
        <Kpi label="Active SKUs" value={number(k?.total_skus)} icon={<Boxes className="size-4" />} hint={`${k?.overstock ?? 0} overstocked`} loading={dash.isLoading} />
        <Kpi label="Low / critical" value={number(k?.low_stock)} icon={<TriangleAlert className="size-4" />} tone={k?.low_stock ? 'warning' : 'good'} hint={`${k?.reorder_needed ?? 0} need reorder`} loading={dash.isLoading} />
        <Kpi label="Out of stock" value={number(k?.out_of_stock)} icon={<PackageX className="size-4" />} tone={k?.out_of_stock ? 'critical' : 'good'} hint="losing sales now" loading={dash.isLoading} />
        <Kpi label="Open POs" value={number(k?.open_purchase_orders)} icon={<ShoppingCart className="size-4" />} hint={`${k?.open_alerts ?? 0} open alerts`} loading={dash.isLoading} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Revenue · last 30 days" description="Daily sales revenue across all warehouses" icon={<TrendingUp className="size-4" />} />
          <div className="px-3 pb-3">{dash.data ? <SalesTrendChart data={dash.data.sales_trend} height={330} /> : <Skeleton className="mx-2 h-80" />}</div>
        </Card>
        <HealthCard />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <BriefingCard />
        <AlertsCard />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <StockoutRadar />
        <Card>
          <CardHeader title="Stock health" description="SKUs by replenishment status" />
          <div className="px-5 pb-5">{dash.data ? <StockHealth data={dash.data.status_breakdown} /> : <Skeleton className="h-40" />}</div>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <ReorderCard />
        <Card>
          <CardHeader title="Stock value by category" />
          <div className="px-5 pb-5">
            {dash.data ? <BarList items={dash.data.category_value.map((c) => ({ label: c.category, value: c.value, key: c.category }))} format={moneyCompact} /> : <Skeleton className="h-48" />}
          </div>
        </Card>
        <LiveActivity />
      </div>
    </div>
  )
}

function HealthCard() {
  const health = useHealth()
  const h = health.data
  const color = !h ? 'var(--border)' : h.score >= 85 ? 'var(--color-good)' : h.score >= 70 ? 'var(--color-warning)' : 'var(--color-critical)'
  const circumference = 2 * Math.PI * 52
  return (
    <Card>
      <CardHeader title="Inventory health score" description="Availability, risk, capital, coverage & accuracy" icon={<Gauge className="size-4" />} />
      <div className="px-5 pb-5">
        {!h ? (
          <Skeleton className="h-56" />
        ) : (
          <>
            <div className="flex items-center gap-5">
              <div className="relative size-32 shrink-0">
                <svg viewBox="0 0 120 120" className="size-32 -rotate-90" role="img" aria-label={`Health score ${h.score} out of 100`}>
                  <circle cx="60" cy="60" r="52" fill="none" stroke="var(--surface-2)" strokeWidth="10" />
                  <circle cx="60" cy="60" r="52" fill="none" stroke={color} strokeWidth="10" strokeLinecap="round" strokeDasharray={`${(h.score / 100) * circumference} ${circumference}`} className="transition-all duration-700" />
                </svg>
                <div className="absolute inset-0 grid place-items-center text-center">
                  <div>
                    <div className="text-3xl font-semibold tabular-nums">{Math.round(h.score)}</div>
                    <div className="text-xs text-muted">grade {h.grade}</div>
                  </div>
                </div>
              </div>
              <p className="text-sm text-muted">{h.focus}</p>
            </div>
            <ul className="mt-4 space-y-2">
              {h.components.map((c) => (
                <li key={c.key} title={c.detail}>
                  <div className="flex justify-between text-xs">
                    <span className="text-muted">{c.label}</span>
                    <span className="tabular-nums font-medium">{Math.round(c.score)}</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
                    <div className="h-full rounded-full bg-[var(--chart-1)]" style={{ width: `${c.score}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </Card>
  )
}

function BriefingCard() {
  const reports = useReports()
  const { can } = useAuth()
  const [speaking, setSpeaking] = useState(false)
  const latest = reports.data?.[0]
  const regenerate = useAction(() => post('/api/jobs/daily_briefing/run'), { success: 'Fresh briefing generated', invalidate: [keys.reports] })
  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title="AI morning briefing"
        description={latest ? `Written by the Copilot agent · ${relativeTime(latest.created_at)}` : 'Generated daily by the Copilot agent'}
        icon={<Bot className="size-4" />}
        action={
          <div className="flex gap-1.5">
            {latest && canSpeak() && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  if (speaking) {
                    stopSpeaking()
                    setSpeaking(false)
                  } else {
                    setSpeaking(true)
                    speak(latest.content, () => setSpeaking(false))
                  }
                }}
              >
                {speaking ? <VolumeX className="size-3.5" /> : <Volume2 className="size-3.5" />}
                {speaking ? 'Stop' : 'Listen'}
              </Button>
            )}
            {can('manager') && (
              <Button variant="secondary" size="sm" onClick={() => regenerate.mutate(undefined)} loading={regenerate.isPending}>
                <RefreshCw className="size-3.5" /> Regenerate
              </Button>
            )}
          </div>
        }
      />
      <div className="max-h-96 overflow-y-auto px-5 pb-5">
        {reports.isLoading ? <Skeleton className="h-48" /> : latest ? <MarkdownView>{latest.content}</MarkdownView> : <EmptyState title="No briefing yet" description="The scheduler writes one every morning." />}
      </div>
    </Card>
  )
}

function AlertsCard() {
  const alerts = useAlerts()
  const list = alerts.data ?? []
  return (
    <Card>
      <CardHeader title="Alerts" description={`${list.length} open`} icon={<TriangleAlert className="size-4" />} />
      <ul className="max-h-96 divide-y divide-border overflow-y-auto">
        {alerts.isLoading && <Skeleton className="m-5 h-32" />}
        {!alerts.isLoading && !list.length && <EmptyState title="All clear" description="No open alerts." />}
        {list.slice(0, 12).map((a) => (
          <li key={a.id} className="flex gap-3 px-5 py-3">
            <SeverityIcon severity={a.severity} className="mt-0.5" />
            <div className="min-w-0">
              <p className="text-sm leading-snug">{a.message}</p>
              <p className="mt-0.5 text-xs text-subtle">
                {titleCase(a.kind)} · {relativeTime(a.created_at)}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}

/** Unique view: when will each item run out, and does an order placed today arrive in time? */
function StockoutRadar() {
  const products = useProducts()
  const HORIZON = 30
  const rows = useMemo(
    () =>
      (products.data ?? [])
        .filter((p): p is ProductRow & { days_of_cover: number } => p.is_active && p.days_of_cover != null && (p.avg_daily_demand ?? 0) > 0 && p.days_of_cover <= HORIZON)
        .sort((a, b) => a.days_of_cover - b.days_of_cover)
        .slice(0, 8),
    [products.data],
  )
  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title="Stockout radar"
        description="Days until each item runs out vs supplier lead time (next 30 days)"
        icon={<Radar className="size-4" />}
        action={
          <div className="hidden items-center gap-3 text-xs text-muted sm:flex">
            <span className="flex items-center gap-1.5"><span className="h-2 w-4 rounded-sm bg-[var(--chart-1)]/60" />Stock left</span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-4 rounded-sm bg-critical/30" />Gap if ordered today</span>
          </div>
        }
      />
      <div className="px-5 pb-5">
        {products.isLoading ? (
          <Skeleton className="h-48" />
        ) : !rows.length ? (
          <EmptyState title="No stockouts in the next 30 days" />
        ) : (
          <ul className="space-y-3">
            {rows.map((p) => {
              const lead = p.lead_time_days ?? 7
              const gap = Math.max(0, Math.min(lead, HORIZON) - p.days_of_cover)
              return (
                <li key={p.id} className="grid grid-cols-[minmax(0,11rem)_1fr_auto] items-center gap-3">
                  <Link to={`/inventory?product=${p.id}`} className="min-w-0 hover:underline">
                    <div className="truncate text-sm">{p.name}</div>
                    <div className="font-mono text-[11px] text-subtle">{p.sku}</div>
                  </Link>
                  <div className="relative h-5 rounded bg-surface-2" title={`${p.days_of_cover} days of cover · ${lead}-day lead time`}>
                    <div className="absolute inset-y-0 left-0 rounded bg-[var(--chart-1)]/60" style={{ width: `${(p.days_of_cover / HORIZON) * 100}%` }} />
                    {gap > 0 && (
                      <div className="absolute inset-y-0 rounded-r bg-critical/30" style={{ left: `${(p.days_of_cover / HORIZON) * 100}%`, width: `${(gap / HORIZON) * 100}%` }} />
                    )}
                    <div className="absolute inset-y-0 w-0.5 bg-fg/50" style={{ left: `${Math.min(99.5, (lead / HORIZON) * 100)}%` }} />
                  </div>
                  <div className="flex w-32 items-center justify-end gap-1.5">
                    <span className={cn('text-xs tabular-nums', p.days_of_cover < lead ? 'font-medium text-critical' : 'text-muted')}>{p.days_of_cover.toFixed(1)}d</span>
                    {p.on_order ? <Badge tone="info">on order</Badge> : <StatusBadge status={p.status} />}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
        <p className="mt-3 text-xs text-subtle">The tick marks the supplier lead time. A red gap means an order placed today still arrives after the stockout.</p>
      </div>
    </Card>
  )
}

function ReorderCard() {
  const recs = useReorder()
  return (
    <Card>
      <CardHeader title="Reorder now" description="EOQ-based, MOQ-rounded" action={<Link to="/insights" className="text-xs text-brand hover:underline">View all</Link>} />
      <ul className="divide-y divide-border">
        {recs.isLoading && <Skeleton className="m-5 h-40" />}
        {recs.data?.slice(0, 6).map((r) => (
          <li key={r.sku} className="flex items-center justify-between gap-3 px-5 py-2.5">
            <div className="min-w-0">
              <div className="truncate text-sm">{r.name}</div>
              <div className="text-xs text-subtle">{r.supplier}</div>
            </div>
            <div className="text-right">
              <div className="text-sm font-medium tabular-nums">× {number(r.suggested_order_qty)}</div>
              <div className="text-xs text-subtle tabular-nums">{money(r.estimated_cost)}</div>
            </div>
          </li>
        ))}
        {recs.data && !recs.data.length && <EmptyState title="Nothing to reorder" />}
      </ul>
    </Card>
  )
}

function LiveActivity() {
  const { events, connected } = useLiveEvents()
  const visible = events.filter((e) => !e.type.startsWith('user.') && e.type !== 'hook.toggled').slice(0, 12)
  return (
    <Card>
      <CardHeader title="Live activity" description={connected ? 'Streaming domain events' : 'Connecting…'} icon={<Activity className="size-4" />} />
      <ul className="max-h-80 space-y-3 overflow-y-auto px-5 pb-5">
        {!visible.length && <p className="text-sm text-muted">Events appear here in real time — try adjusting stock or chatting with Copilot.</p>}
        {visible.map((e) => (
          <li key={e.id} className="flex gap-2.5 animate-fade-in">
            <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-brand" />
            <div className="min-w-0 text-sm">
              <div className="flex flex-wrap items-center gap-1.5">
                <code className="text-xs font-medium">{e.type}</code>
                <Actor actor={e.source} />
              </div>
              <div className="truncate text-xs text-muted">{describeEvent(e.payload)}</div>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function describeEvent(p: Record<string, unknown>): string {
  if (p.sku && p.delta != null) return `${p.name} ${Number(p.delta) > 0 ? '+' : ''}${p.delta} → ${p.on_hand} on hand`
  if (p.number) return `${p.number}${p.status ? ` · ${p.status}` : ''}${p.total ? ` · ${money(Number(p.total))}` : ''}`
  if (p.tool) return `${p.agent ?? ''} → ${p.tool}`
  if (p.message) return String(p.message)
  if (p.name) return String(p.name)
  return Object.keys(p).slice(0, 4).join(', ')
}

function TodayBillingCard() {
  const s = useBillingSummary(7).data
  if (!s) return null
  return (
    <Link to="/billing" className="group block h-full">
      <Card className="flex h-full items-center gap-4 p-4 transition group-hover:border-brand/50">
        <div className="grid size-11 place-items-center rounded-xl bg-brand-soft text-brand"><Receipt className="size-5" /></div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">Today: {money(s.today.sales)} from {s.today.bills} bill{s.today.bills === 1 ? '' : 's'}</div>
          <div className="text-sm text-muted">
            {s.outstanding ? <><span className="font-medium text-critical">{money(s.outstanding)}</span> udhaar to collect from {s.customers_with_dues} customer{s.customers_with_dues === 1 ? '' : 's'}</> : 'No udhaar pending'} · 7 days {moneyCompact(s.period.sales)}
          </div>
        </div>
        <ChevronRight className="size-5 text-muted transition group-hover:translate-x-0.5" />
      </Card>
    </Link>
  )
}
