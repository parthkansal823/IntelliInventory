/** Inventory-specific display components. */
import {
  ArrowDownRight,
  ArrowUpRight,
  Bot,
  CircleAlert,
  CircleCheck,
  CircleX,
  Info,
  PackageX,
  TriangleAlert,
  Warehouse as WarehouseIcon,
} from 'lucide-react'
import { lazy, Suspense, type ReactNode } from 'react'
import type { POStatus, StockStatus } from '@/lib/types'
import { actorLabel, cn } from '@/lib/utils'
import { Badge, Card, Skeleton, type Tone } from './ui'
import { useT } from '@/lib/i18n'

const Markdown = lazy(() => import('./Markdown'))

export const STATUS: Record<StockStatus, { label: string; tone: Tone; icon: typeof CircleCheck; color: string }> = {
  healthy: { label: 'Healthy', tone: 'good', icon: CircleCheck, color: 'var(--color-good)' },
  low: { label: 'Low', tone: 'warning', icon: TriangleAlert, color: 'var(--color-warning)' },
  critical: { label: 'Critical', tone: 'serious', icon: CircleAlert, color: 'var(--color-serious)' },
  out: { label: 'Out of stock', tone: 'critical', icon: PackageX, color: 'var(--color-critical)' },
  overstock: { label: 'Overstock', tone: 'info', icon: WarehouseIcon, color: 'var(--chart-1)' },
}

export function StatusBadge({ status }: { status?: StockStatus }) {
  const t = useT()
  if (!status) return null
  const s = STATUS[status]
  const Icon = s.icon
  return (
    <Badge tone={s.tone}>
      <Icon className="size-3" />
      {t(s.label)}
    </Badge>
  )
}

const PO_TONES: Record<POStatus, Tone> = { draft: 'neutral', approved: 'brand', ordered: 'info', received: 'good', cancelled: 'critical' }
export function POStatusBadge({ status }: { status: POStatus }) {
  return <Badge tone={PO_TONES[status]} className="capitalize">{status}</Badge>
}

export function SeverityIcon({ severity, className }: { severity: string; className?: string }) {
  const t = useT()
  if (severity === 'critical') return <CircleX className={cn('size-4 shrink-0 text-critical', className)} aria-label={t('critical')} />
  if (severity === 'warning') return <TriangleAlert className={cn('size-4 shrink-0 text-[#d18f00] dark:text-warning', className)} aria-label={t('warning')} />
  return <Info className={cn('size-4 shrink-0 text-[#2a78d6] dark:text-[#86b6ef]', className)} aria-label={t('info')} />
}

/** On-hand vs reorder point: bar fills to on-hand, tick marks the reorder point. */
export function StockBar({ onHand = 0, reorderPoint = 0, status }: { onHand?: number; reorderPoint?: number; status?: StockStatus }) {
  const max = Math.max(onHand, reorderPoint * 2, 1)
  const color = status ? STATUS[status].color : 'var(--chart-1)'
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-1.5 w-24 overflow-hidden rounded-full bg-surface-2" aria-hidden>
        <div className="h-full rounded-full" style={{ width: `${Math.min(100, (onHand / max) * 100)}%`, background: color }} />
        <div className="absolute top-0 h-full w-0.5 bg-fg/40" style={{ left: `${Math.min(99, (reorderPoint / max) * 100)}%` }} />
      </div>
      <span className="text-sm tabular-nums">{onHand.toLocaleString('en-IN')}</span>
    </div>
  )
}

export function Kpi({ label, value, icon, hint, delta, tone, loading }: { label: string; value: ReactNode; icon: ReactNode; hint?: ReactNode; delta?: number | null; tone?: 'critical' | 'warning' | 'good'; loading?: boolean }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted">{label}</span>
        <span
          className={cn(
            'rounded-lg p-1.5',
            tone === 'critical' ? 'bg-critical/10 text-critical' : tone === 'warning' ? 'bg-warning/15 text-[#b07800] dark:text-warning' : tone === 'good' ? 'bg-good/10 text-good' : 'bg-brand-soft text-brand',
          )}
        >
          {icon}
        </span>
      </div>
      {loading ? <Skeleton className="mt-3 h-7 w-24" /> : <div className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">{value}</div>}
      <div className="mt-1 flex items-center gap-1.5 text-xs text-muted">
        {delta != null && (
          <span className={cn('inline-flex items-center font-medium', delta >= 0 ? 'text-good' : 'text-critical')}>
            {delta >= 0 ? <ArrowUpRight className="size-3.5" /> : <ArrowDownRight className="size-3.5" />}
            {Math.abs(delta).toFixed(1)}%
          </span>
        )}
        {hint}
      </div>
    </Card>
  )
}

export function Actor({ actor }: { actor: string }) {
  const { label, isAgent } = actorLabel(actor)
  return isAgent ? (
    <Badge tone="brand" className="capitalize">
      <Bot className="size-3" />
      {label}
    </Badge>
  ) : (
    <span className="text-xs text-muted">{label}</span>
  )
}

export function MarkdownView({ children, className }: { children: string; className?: string }) {
  return (
    <Suspense fallback={<p className={cn('prose-chat whitespace-pre-wrap', className)}>{children}</p>}>
      <Markdown className={className}>{children}</Markdown>
    </Suspense>
  )
}

export const AGENT_COLORS: Record<string, string> = {
  copilot: '#6366f1',
  analyst: '#0ea5e9',
  forecaster: '#10b981',
  procurement: '#f59e0b',
  auditor: '#ec4899',
  autopilot: '#8b5cf6',
}
