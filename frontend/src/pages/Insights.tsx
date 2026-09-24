import { FlaskConical, Play, ShoppingCart, Tag } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { BarList, ForecastChart, SimulationChart } from '@/components/charts'
import { SeverityIcon, StatusBadge } from '@/components/domain'
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, PageHeader, Select, Skeleton, Table, Tabs, TabsContent, TabsList, TabsTrigger, Td, Th } from '@/components/ui'
import { keys, useAbc, useAction, useAnomalies, useForecast, useMargins, useMarkdowns, useProducts, useReorder, useSupplierScores } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { post } from '@/lib/api'
import type { Simulation } from '@/lib/types'
import { cn, money, moneyCompact, number, pct, titleCase } from '@/lib/utils'

export default function Insights() {
  return (
    <div>
      <PageHeader title="Insights" description="Forecasts, replenishment, pricing and risk — computed live from your ledger." />
      <Tabs defaultValue="reorder">
        <TabsList>
          <TabsTrigger value="reorder">Reorder plan</TabsTrigger>
          <TabsTrigger value="forecast">Forecast & what-if</TabsTrigger>
          <TabsTrigger value="markdowns">Smart markdowns</TabsTrigger>
          <TabsTrigger value="abc">ABC analysis</TabsTrigger>
          <TabsTrigger value="anomalies">Anomalies</TabsTrigger>
          <TabsTrigger value="suppliers">Suppliers</TabsTrigger>
          <TabsTrigger value="margins">Margins</TabsTrigger>
        </TabsList>
        <TabsContent value="reorder"><ReorderPlan /></TabsContent>
        <TabsContent value="forecast"><ForecastLab /></TabsContent>
        <TabsContent value="markdowns"><Markdowns /></TabsContent>
        <TabsContent value="abc"><Abc /></TabsContent>
        <TabsContent value="anomalies"><Anomalies /></TabsContent>
        <TabsContent value="suppliers"><Suppliers /></TabsContent>
        <TabsContent value="margins"><Margins /></TabsContent>
      </Tabs>
    </div>
  )
}

function ReorderPlan() {
  const recs = useReorder()
  const { can } = useAuth()
  const navigate = useNavigate()
  const [picked, setPicked] = useState<Set<number>>(new Set())
  useEffect(() => setPicked(new Set(recs.data?.map((r) => r.product_id))), [recs.data])
  const create = useAction(() => post<unknown[]>('/api/purchase-orders/from-recommendations', { product_ids: [...picked] }), {
    success: (r) => `Drafted ${r.length} PO(s) — one per supplier`,
    invalidate: [['purchase-orders'], keys.reorder, keys.dashboard],
    onSuccess: () => navigate('/purchase-orders'),
  })
  const total = recs.data?.filter((r) => picked.has(r.product_id)).reduce((s, r) => s + r.estimated_cost, 0) ?? 0
  const toggle = (id: number) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n })

  return (
    <Card>
      <CardHeader
        title="Replenishment plan"
        description="Items at or below their reorder point · quantities = max(EOQ, gap to ROP + lead-time demand), rounded to MOQ"
        action={can('staff') && (
          <Button onClick={() => create.mutate(undefined)} disabled={!picked.size} loading={create.isPending}>
            <ShoppingCart className="size-4" /> Draft POs · {moneyCompact(total)}
          </Button>
        )}
      />
      {recs.isLoading ? <Skeleton className="m-5 h-48" /> : !recs.data?.length ? <EmptyState title="Nothing to reorder 🎉" /> : (
        <Table>
          <thead>
            <tr>
              <Th className="w-8" />
              <Th>Product</Th>
              <Th>Supplier</Th>
              <Th>Status</Th>
              <Th className="text-right">On hand</Th>
              <Th className="text-right">ROP</Th>
              <Th className="text-right">Order qty</Th>
              <Th className="text-right">Cost</Th>
              <Th>Why</Th>
            </tr>
          </thead>
          <tbody>
            {recs.data.map((r) => (
              <tr key={r.product_id} className="hover:bg-surface-2/60">
                <Td><input type="checkbox" checked={picked.has(r.product_id)} onChange={() => toggle(r.product_id)} className="size-4 accent-[var(--brand)]" aria-label={`Include ${r.sku}`} /></Td>
                <Td><div className="font-medium">{r.name}</div><div className="font-mono text-xs text-subtle">{r.sku}</div></Td>
                <Td className="text-muted">{r.supplier}</Td>
                <Td><StatusBadge status={r.status} /></Td>
                <Td className="text-right tabular-nums">{number(r.on_hand)}</Td>
                <Td className="text-right tabular-nums">{number(r.reorder_point)}</Td>
                <Td className="text-right font-medium tabular-nums">{number(r.suggested_order_qty)}</Td>
                <Td className="text-right tabular-nums">{money(r.estimated_cost)}</Td>
                <Td className="max-w-64 text-xs text-muted">{r.reason}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

function ForecastLab() {
  const products = useProducts()
  const sorted = useMemo(() => [...(products.data ?? [])].filter((p) => p.is_active).sort((a, b) => (b.avg_daily_demand ?? 0) * b.unit_price - (a.avg_daily_demand ?? 0) * a.unit_price), [products.data])
  const [productId, setProductId] = useState<number | null>(null)
  const id = productId ?? sorted[0]?.id ?? null
  const product = sorted.find((p) => p.id === id)
  const forecast = useForecast(id)
  const [form, setForm] = useState({ demand: 100, lead: '', service: 95, qty: '' })
  const [result, setResult] = useState<{ base: Simulation; scenario: Simulation } | null>(null)
  const sim = useAction(async () => {
    const payload = { product_id: id, horizon: 60 }
    const [base, scenario] = await Promise.all([
      post<Simulation>('/api/analytics/simulate', payload),
      post<Simulation>('/api/analytics/simulate', {
        ...payload,
        demand_multiplier: form.demand / 100,
        lead_time_days: form.lead ? Number(form.lead) : null,
        service_level: form.service / 100,
        order_qty: form.qty ? Number(form.qty) : null,
      }),
    ])
    return { base, scenario }
  }, { onSuccess: setResult })
  useEffect(() => setResult(null), [id])

  const metrics: [string, keyof Simulation['results'], (v: number) => string, boolean][] = [
    ['Fill rate', 'fill_rate', (v) => pct(v), true],
    ['Stockout risk', 'stockout_probability', (v) => pct(v), false],
    ['Stockout days', 'expected_stockout_days', (v) => v.toFixed(1), false],
    ['Avg inventory', 'avg_inventory', (v) => number(Math.round(v)), false],
    ['Holding cost', 'holding_cost', money, false],
    ['Lost sales', 'lost_sales_value', money, false],
  ]

  return (
    <div className="grid gap-4 xl:grid-cols-5">
      <Card className="xl:col-span-3">
        <CardHeader
          title="Demand forecast"
          description={forecast.data ? `Holt-Winters (weekly season) · backtest MAPE ${forecast.data.mape ?? '—'}% · next 30 days ≈ ${forecast.data.total_forecast} units` : 'Holt-Winters with weekly seasonality'}
          action={
            <Select value={id ?? ''} onChange={(e) => setProductId(Number(e.target.value))} className="w-64">
              {sorted.map((p) => <option key={p.id} value={p.id}>{p.sku} — {p.name}</option>)}
            </Select>
          }
        />
        <div className="px-5 pb-5">{forecast.data ? <ForecastChart data={forecast.data} height={300} /> : <Skeleton className="h-72" />}</div>
      </Card>

      <Card className="xl:col-span-2">
        <CardHeader title="What-if simulator" description="300 Monte-Carlo runs of the (s, Q) policy over 60 days" icon={<FlaskConical className="size-4" />} />
        <form className="grid grid-cols-2 gap-3 px-5 pb-5" onSubmit={(e) => { e.preventDefault(); sim.mutate(undefined) }}>
          <Field label={`Demand ${form.demand >= 100 ? '+' : ''}${form.demand - 100}%`} className="col-span-2">
            <input type="range" min={50} max={200} step={5} value={form.demand} onChange={(e) => setForm({ ...form, demand: Number(e.target.value) })} className="w-full accent-[var(--brand)]" />
          </Field>
          <Field label={`Service level ${form.service}%`} className="col-span-2">
            <input type="range" min={80} max={99.5} step={0.5} value={form.service} onChange={(e) => setForm({ ...form, service: Number(e.target.value) })} className="w-full accent-[var(--brand)]" />
          </Field>
          <Field label="Lead time (days)" hint={`current ${product?.lead_time_days ?? '—'}d`}>
            <Input type="number" min={1} value={form.lead} onChange={(e) => setForm({ ...form, lead: e.target.value })} placeholder="current" />
          </Field>
          <Field label="Order qty" hint={`EOQ ${product?.eoq ?? '—'}`}>
            <Input type="number" min={1} value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })} placeholder="EOQ" />
          </Field>
          <Button type="submit" className="col-span-2" loading={sim.isPending} disabled={!id}>
            <Play className="size-4" /> Run simulation
          </Button>
        </form>
      </Card>

      {result && (
        <Card className="xl:col-span-5">
          <CardHeader
            title={`Scenario vs current policy — ${result.scenario.product.name}`}
            description={`Scenario: safety stock ${result.scenario.policy.safety_stock}, reorder point ${result.scenario.policy.reorder_point}, order qty ${result.scenario.policy.order_qty} · current: ${result.base.policy.safety_stock} / ${result.base.policy.reorder_point} / ${result.base.policy.order_qty}`}
          />
          <div className="grid gap-4 px-5 pb-5 lg:grid-cols-5">
            <div className="grid grid-cols-2 content-start gap-2 lg:col-span-2">
              {metrics.map(([label, key, fmt, higherIsBetter]) => {
                const a = result.base.results[key]
                const b = result.scenario.results[key]
                const better = b === a ? null : higherIsBetter ? b > a : b < a
                return (
                  <div key={key} className="rounded-lg border border-border p-3">
                    <div className="text-xs text-muted">{label}</div>
                    <div className="mt-1 text-lg font-semibold tabular-nums">{fmt(b)}</div>
                    <div className={cn('text-xs tabular-nums', better == null ? 'text-subtle' : better ? 'text-good' : 'text-critical')}>was {fmt(a)}</div>
                  </div>
                )
              })}
            </div>
            <div className="lg:col-span-3"><SimulationChart sim={result.scenario} /></div>
          </div>
        </Card>
      )}
    </div>
  )
}

function Markdowns() {
  const md = useMarkdowns()
  const total = md.data?.reduce((s, m) => s + m.capital_tied, 0) ?? 0
  return (
    <Card>
      <CardHeader
        title="Smart markdown advisor"
        description={`Overstocked & slow-moving items · ${money(total)} of capital tied up · discounts clear excess in ~60 days and never go below cost + 5%`}
        icon={<Tag className="size-4" />}
      />
      {md.isLoading ? <Skeleton className="m-5 h-40" /> : !md.data?.length ? <EmptyState title="No excess stock worth discounting" /> : (
        <Table>
          <thead>
            <tr>
              <Th>Product</Th>
              <Th className="text-right">Cover</Th>
              <Th className="text-right">Excess units</Th>
              <Th className="text-right">Capital tied</Th>
              <Th className="text-right">Discount</Th>
              <Th className="text-right">Price</Th>
              <Th className="text-right">Margin after</Th>
              <Th>Recommendation</Th>
            </tr>
          </thead>
          <tbody>
            {md.data.map((m) => (
              <tr key={m.product_id}>
                <Td><div className="font-medium">{m.name}</div><div className="font-mono text-xs text-subtle">{m.sku}</div></Td>
                <Td className="text-right tabular-nums">{Math.round(m.days_of_cover)}d</Td>
                <Td className="text-right tabular-nums">{number(m.excess_units)}</Td>
                <Td className="text-right tabular-nums">{money(m.capital_tied)}</Td>
                <Td className="text-right"><Badge tone="warning">−{m.suggested_discount_pct}%</Badge></Td>
                <Td className="text-right tabular-nums"><span className="text-subtle line-through">{money(m.current_price)}</span> {money(m.new_price)}</Td>
                <Td className="text-right tabular-nums">{pct(m.margin_after_pct)}</Td>
                <Td className="text-xs text-muted">{m.action}{m.projected_days_to_clear ? ` · clears in ~${m.projected_days_to_clear}d` : ''}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

function Abc() {
  const abc = useAbc()
  if (!abc.data) return <Skeleton className="h-64" />
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {abc.data.classes.map((c) => (
        <Card key={c.class} className="p-5">
          <div className="flex items-center justify-between">
            <Badge tone={c.class === 'A' ? 'brand' : 'neutral'} className="text-sm">Class {c.class}</Badge>
            <span className="text-xs text-muted">{c.count} SKUs</span>
          </div>
          <div className="mt-3 text-2xl font-semibold tabular-nums">{moneyCompact(c.consumption_value)}<span className="text-sm font-normal text-muted"> / month</span></div>
          <div className="text-xs text-muted">{moneyCompact(c.stock_value)} in stock</div>
          <p className="mt-2 text-xs text-subtle">
            {c.class === 'A' ? 'Top 80% of consumption value — count often, highest service level.' : c.class === 'B' ? 'Next 15% — standard policies.' : 'Last 5% — simplify, order in bulk.'}
          </p>
        </Card>
      ))}
      <Card className="lg:col-span-3">
        <CardHeader title="Monthly consumption value by product" description="Pareto ordering" />
        <div className="px-5 pb-5">
          <BarList items={abc.data.products.slice(0, 15).map((p) => ({ key: p.sku, label: <span>{p.name} <Badge tone={p.class === 'A' ? 'brand' : 'neutral'}>{p.class}</Badge></span>, value: p.monthly_consumption_value }))} format={moneyCompact} />
        </div>
      </Card>
    </div>
  )
}

function Anomalies() {
  const an = useAnomalies()
  const navigate = useNavigate()
  if (an.isLoading) return <Skeleton className="h-48" />
  if (!an.data?.length) return <Card><EmptyState title="No anomalies detected" description="Demand and write-offs look normal this week." /></Card>
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {an.data.map((a, i) => (
        <Card key={i} className="p-4">
          <div className="flex items-start gap-3">
            <SeverityIcon severity={a.severity} className="mt-0.5" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-medium">{titleCase(a.kind)}</span>
                <Badge tone={a.severity === 'critical' ? 'critical' : 'warning'}>{a.severity}</Badge>
                {a.z_score != null && <span className="text-xs text-subtle">z = {a.z_score}</span>}
              </div>
              <p className="mt-1 text-sm text-muted">{a.message}</p>
              <Button size="sm" variant="ghost" className="mt-2 -ml-2" onClick={() => navigate(`/copilot?q=${encodeURIComponent(`Investigate the ${a.kind.replace('_', ' ')} on ${a.sku} and recommend an action`)}`)}>
                Investigate with Auditor →
              </Button>
            </div>
          </div>
        </Card>
      ))}
    </div>
  )
}

function Suppliers() {
  const s = useSupplierScores()
  if (!s.data) return <Skeleton className="h-48" />
  return (
    <Card>
      <CardHeader title="Supplier scorecards" description="Score = 60% on-time delivery + 25% lead-time accuracy + 15% catalog rating (last 120 days)" />
      <Table>
        <thead>
          <tr>
            <Th>Supplier</Th>
            <Th>Grade</Th>
            <Th>On-time</Th>
            <Th className="text-right">Lead time</Th>
            <Th className="text-right">Orders</Th>
            <Th className="text-right">Spend</Th>
            <Th className="text-right">Products</Th>
          </tr>
        </thead>
        <tbody>
          {s.data.map((sup) => (
            <tr key={sup.id}>
              <Td><div className="font-medium">{sup.name}</div><div className="text-xs text-subtle">{sup.email}</div></Td>
              <Td><Badge tone={sup.grade === 'A' ? 'good' : sup.grade === 'B' ? 'info' : 'warning'}>{sup.grade} · {sup.score}</Badge></Td>
              <Td>
                <div className="flex items-center gap-2">
                  <div className="h-1.5 w-20 overflow-hidden rounded-full bg-surface-2"><div className="h-full rounded-full bg-[var(--chart-1)]" style={{ width: `${sup.on_time_rate ?? 0}%` }} /></div>
                  <span className="text-xs tabular-nums">{pct(sup.on_time_rate, 0)}</span>
                </div>
              </Td>
              <Td className="text-right text-xs tabular-nums">{sup.promised_lead_time}d → <span className={cn((sup.actual_lead_time ?? 0) > sup.promised_lead_time ? 'text-critical' : 'text-good')}>{sup.actual_lead_time ?? '—'}d</span></Td>
              <Td className="text-right tabular-nums">{sup.orders_received}{sup.open_orders ? <span className="text-xs text-subtle"> +{sup.open_orders} open</span> : null}</Td>
              <Td className="text-right tabular-nums">{moneyCompact(sup.spend)}</Td>
              <Td className="text-right tabular-nums">{sup.products}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  )
}

function Margins() {
  const m = useMargins()
  if (!m.data) return <Skeleton className="h-48" />
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Gross margin % by category" description="Last 30 days of sales" />
        <div className="px-5 pb-5"><BarList items={[...m.data].sort((a, b) => b.margin_pct - a.margin_pct).map((c) => ({ key: c.category, label: c.category, value: c.margin_pct }))} format={(v) => pct(v)} max={100} /></div>
      </Card>
      <Card>
        <CardHeader title="Revenue & profit" />
        <Table>
          <thead><tr><Th>Category</Th><Th className="text-right">Revenue</Th><Th className="text-right">Gross profit</Th><Th className="text-right">Units</Th></tr></thead>
          <tbody>
            {m.data.map((c) => (
              <tr key={c.category}>
                <Td>{c.category}</Td>
                <Td className="text-right tabular-nums">{moneyCompact(c.revenue)}</Td>
                <Td className="text-right tabular-nums">{moneyCompact(c.gross_profit)}</Td>
                <Td className="text-right tabular-nums">{number(c.units)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </div>
  )
}
