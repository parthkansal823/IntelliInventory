/**
 * Charts. Follows the dataviz method: one axis, thin 2px lines, recessive grid,
 * validated categorical slots (--chart-1..3, light/dark stepped), status colors
 * only with icon + label, text in text tokens, hover tooltip on every plot.
 */
import type { ReactNode } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ForecastData, Simulation, StockStatus } from '@/lib/types'
import { cn, money, moneyCompact, number, numberCompact, shortDate } from '@/lib/utils'
import { STATUS } from './domain'

const axis = { stroke: 'var(--chart-axis)', fontSize: 11, tickLine: false, axisLine: false } as const
const grid = <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="0" vertical={false} />

type TipRow = { label: string; value: string; color?: string; dashed?: boolean }

function TooltipCard({ title, rows }: { title: string; rows: TipRow[] }) {
  return (
    <div className="min-w-36 rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium text-fg">{title}</div>
      {rows.map((r) => (
        <div key={r.label} className="flex items-center justify-between gap-4 py-0.5">
          <span className="flex items-center gap-1.5 text-muted">
            {r.color && <span className="inline-block h-0.5 w-3 rounded" style={{ background: r.color, opacity: r.dashed ? 0.5 : 1 }} />}
            {r.label}
          </span>
          <span className="font-medium tabular-nums text-fg">{r.value}</span>
        </div>
      ))}
    </div>
  )
}

type AnyTooltip = { active?: boolean; payload?: readonly { payload?: Record<string, number | string> }[] }
const point = (p: unknown) => {
  const t = p as AnyTooltip
  return t.active && t.payload?.length ? (t.payload[0].payload as Record<string, number | string>) : null
}

// --- Revenue trend (single series: title names it, no legend) --------------------------------------

export function SalesTrendChart({ data, height = 240 }: { data: { date: string; revenue: number; units: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="rev-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.22} />
            <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
          </linearGradient>
        </defs>
        {grid}
        <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={28} {...axis} />
        <YAxis tickFormatter={(v) => moneyCompact(v)} width={52} {...axis} />
        <Tooltip
          cursor={{ stroke: 'var(--chart-axis)', strokeWidth: 1, strokeDasharray: '3 3' }}
          content={(p: unknown) => {
            const d = point(p)
            return d ? <TooltipCard title={shortDate(String(d.date))} rows={[{ label: 'Revenue', value: money(Number(d.revenue)), color: 'var(--chart-1)' }, { label: 'Units sold', value: number(Number(d.units)) }]} /> : null
          }}
        />
        <Area type="monotone" dataKey="revenue" stroke="var(--chart-1)" strokeWidth={2} fill="url(#rev-fill)" activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface)' }} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

// --- Forecast: actual vs forecast with 80% band -------------------------------------------------------

export function ForecastChart({ data, height = 260, historyDays = 45 }: { data: ForecastData; height?: number; historyDays?: number }) {
  type Row = { date: string; actual?: number; forecast?: number; band?: [number, number] }
  const history = data.history.slice(-historyDays)
  const rows: Row[] = history.map((h, i) =>
    // the last actual point also starts the forecast line so the two connect
    i === history.length - 1 ? { date: h.date, actual: h.actual, forecast: h.actual, band: [h.actual, h.actual] } : { date: h.date, actual: h.actual },
  )
  rows.push(...data.forecast.map((f): Row => ({ date: f.date, forecast: f.forecast, band: [f.lower, f.upper] })))
  return (
    <div>
      <Legend items={[{ label: 'Actual units sold', color: 'var(--chart-1)' }, { label: 'Forecast', color: 'var(--chart-2)' }, { label: '80% range', color: 'var(--chart-2)', band: true }]} />
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          {grid}
          <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={32} {...axis} />
          <YAxis width={40} tickFormatter={(v) => numberCompact(v)} {...axis} />
          <Tooltip
            cursor={{ stroke: 'var(--chart-axis)', strokeWidth: 1, strokeDasharray: '3 3' }}
            content={(p: unknown) => {
              const d = point(p) as Record<string, unknown> | null
              if (!d) return null
              const out: TipRow[] = []
              if (d.actual != null) out.push({ label: 'Actual', value: number(Number(d.actual)), color: 'var(--chart-1)' })
              if (d.forecast != null) out.push({ label: 'Forecast', value: Number(d.forecast).toFixed(1), color: 'var(--chart-2)' })
              if (Array.isArray(d.band) && d.actual == null) out.push({ label: '80% range', value: `${d.band[0]} – ${d.band[1]}`, color: 'var(--chart-2)', dashed: true })
              return <TooltipCard title={shortDate(String(d.date))} rows={out} />
            }}
          />
          <Area type="monotone" dataKey="band" stroke="none" fill="var(--chart-2)" fillOpacity={0.14} activeDot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="actual" stroke="var(--chart-1)" strokeWidth={2} dot={false} animationDuration={500} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface)' }} />
          <Line type="monotone" dataKey="forecast" stroke="var(--chart-2)" strokeWidth={2} dot={false} animationDuration={500} strokeDasharray="5 4" activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface)' }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

// --- Simulation: projected stock (median + P10–P90 band) vs reorder point --------------------------

export function SimulationChart({ sim, height = 260 }: { sim: Simulation; height?: number }) {
  const rows = sim.projection.map((p) => ({ ...p, band: [p.p10, p.p90] as [number, number] }))
  return (
    <div>
      <Legend items={[{ label: 'Median stock', color: 'var(--chart-1)' }, { label: 'P10–P90 range', color: 'var(--chart-1)', band: true }, { label: 'Reorder point', color: 'var(--chart-axis)', dashed: true }]} />
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          {grid}
          <XAxis dataKey="day" tickFormatter={(d) => `D${d}`} minTickGap={24} {...axis} />
          <YAxis width={44} tickFormatter={(v) => numberCompact(v)} {...axis} />
          <Tooltip
            cursor={{ stroke: 'var(--chart-axis)', strokeWidth: 1, strokeDasharray: '3 3' }}
            content={(p: unknown) => {
              const d = point(p)
              return d ? (
                <TooltipCard
                  title={`Day ${d.day}`}
                  rows={[
                    { label: 'Median stock', value: number(Number(d.p50)), color: 'var(--chart-1)' },
                    { label: 'P10 – P90', value: `${number(Number(d.p10))} – ${number(Number(d.p90))}`, color: 'var(--chart-1)', dashed: true },
                    { label: 'Expected demand', value: Number(d.demand).toFixed(1) },
                  ]}
                />
              ) : null
            }}
          />
          <Area type="stepAfter" dataKey="band" stroke="none" fill="var(--chart-1)" fillOpacity={0.14} activeDot={false} isAnimationActive={false} />
          <ReferenceLine y={sim.policy.reorder_point} stroke="var(--chart-axis)" strokeDasharray="4 4" strokeWidth={1.5} />
          <Line type="stepAfter" dataKey="p50" stroke="var(--chart-1)" strokeWidth={2} dot={false} animationDuration={500} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface)' }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

// --- HTML bar list: magnitude by category (single hue, direct labels, hover title) ------------------

export function BarList({ items, format = money, color = 'var(--chart-1)', max }: { items: { label: ReactNode; value: number; hint?: string; key?: string }[]; format?: (v: number) => string; color?: string; max?: number }) {
  const top = max ?? Math.max(...items.map((i) => i.value), 1)
  return (
    <ul className="space-y-2.5">
      {items.map((item, i) => (
        <li key={item.key ?? i} className="group" title={`${item.hint ?? ''}${format(item.value)}`}>
          <div className="mb-1 flex items-baseline justify-between gap-3 text-xs">
            <span className="truncate text-fg">{item.label}</span>
            <span className="font-medium tabular-nums text-muted group-hover:text-fg">{format(item.value)}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full transition-all group-hover:opacity-80" style={{ width: `${Math.max(2, (item.value / top) * 100)}%`, background: color }} />
          </div>
        </li>
      ))}
    </ul>
  )
}

// --- Stock health: segmented bar + labelled rows (status color always with icon + label) ------------

export function StockHealth({ data }: { data: { status: StockStatus; count: number }[] }) {
  const total = data.reduce((s, d) => s + d.count, 0) || 1
  return (
    <div>
      <div className="mb-4 flex h-3 gap-0.5 overflow-hidden rounded-full" role="img" aria-label="Stock health distribution">
        {data.filter((d) => d.count).map((d) => (
          <div key={d.status} title={`${STATUS[d.status].label}: ${d.count}`} className="h-full first:rounded-l-full last:rounded-r-full" style={{ width: `${(d.count / total) * 100}%`, background: STATUS[d.status].color }} />
        ))}
      </div>
      <ul className="space-y-2">
        {data.map((d) => {
          const s = STATUS[d.status]
          const Icon = s.icon
          return (
            <li key={d.status} className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 text-muted">
                <Icon className="size-4" style={{ color: s.color }} />
                {s.label}
              </span>
              <span className="tabular-nums">
                <span className="font-medium text-fg">{d.count}</span>
                <span className="ml-1.5 text-xs text-subtle">{Math.round((d.count / total) * 100)}%</span>
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function Legend({ items, className }: { items: { label: string; color: string; band?: boolean; dashed?: boolean }[]; className?: string }) {
  return (
    <div className={cn('mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted', className)}>
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          {i.band ? (
            <span className="inline-block h-2.5 w-3.5 rounded-sm" style={{ background: i.color, opacity: 0.25 }} />
          ) : (
            <span className="inline-block h-0.5 w-3.5 rounded" style={{ background: i.dashed ? `repeating-linear-gradient(90deg, ${i.color} 0 3px, transparent 3px 5px)` : i.color }} />
          )}
          {i.label}
        </span>
      ))}
    </div>
  )
}
