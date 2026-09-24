import { PackageCheck, Printer, Send, ShoppingCart, Sparkles, ThumbsUp, X } from 'lucide-react'
import { useState } from 'react'
import { Actor, POStatusBadge } from '@/components/domain'
import { Button, Card, Dialog, EmptyState, PageHeader, Skeleton, Table, Tabs, TabsList, TabsTrigger, Td, Th } from '@/components/ui'
import { keys, useAction, usePOStats, usePurchaseOrders } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { post } from '@/lib/api'
import type { POStatus, PurchaseOrder } from '@/lib/types'
import { dateTime, money, number, shortDate } from '@/lib/utils'

const TABS: { value: string; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'draft', label: 'Drafts' },
  { value: 'approved', label: 'Approved' },
  { value: 'ordered', label: 'Ordered' },
  { value: 'received', label: 'Received' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'all', label: 'All' },
]
const invalidate = [['purchase-orders'], keys.dashboard, keys.reorder, keys.products, ['health']]

export default function PurchaseOrders() {
  const [tab, setTab] = useState('open')
  const orders = usePurchaseOrders(tab)
  const stats = usePOStats()
  const { can } = useAuth()
  const [selected, setSelected] = useState<PurchaseOrder | null>(null)
  const generate = useAction(() => post<PurchaseOrder[]>('/api/purchase-orders/from-recommendations', {}), {
    success: (r) => `Drafted ${r.length} purchase order(s) from recommendations`,
    invalidate,
  })
  const count = (v: string) =>
    v === 'open' ? (stats.data?.draft ?? 0) + (stats.data?.approved ?? 0) + (stats.data?.ordered ?? 0) : v === 'all' ? Object.values(stats.data ?? {}).reduce((a, b) => a + b, 0) : (stats.data?.[v] ?? 0)

  return (
    <div>
      <PageHeader
        title="Purchase orders"
        description="Draft → approved → ordered → received. Agents draft; managers approve."
        actions={
          can('staff') && (
            <Button onClick={() => generate.mutate(undefined)} loading={generate.isPending}>
              <Sparkles className="size-4" /> Generate from recommendations
            </Button>
          )
        }
      />
      <Card>
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="px-3">
            {TABS.map((t) => (
              <TabsTrigger key={t.value} value={t.value}>
                {t.label}
                <span className="rounded-full bg-surface-2 px-1.5 text-[10px] tabular-nums text-muted">{count(t.value)}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        {orders.isLoading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : !orders.data?.length ? (
          <EmptyState icon={<ShoppingCart className="size-5" />} title="No purchase orders here" description="Generate drafts from recommendations or ask the Procurement agent." />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>PO</Th>
                <Th>Supplier</Th>
                <Th>Status</Th>
                <Th>Created by</Th>
                <Th className="text-right">Lines</Th>
                <Th className="text-right">Units</Th>
                <Th className="text-right">Total</Th>
                <Th>Expected</Th>
              </tr>
            </thead>
            <tbody>
              {orders.data.map((po) => (
                <tr key={po.id} onClick={() => setSelected(po)} className="cursor-pointer hover:bg-surface-2/60">
                  <Td className="font-mono text-xs font-medium">{po.number}</Td>
                  <Td>{po.supplier?.name}</Td>
                  <Td><POStatusBadge status={po.status} /></Td>
                  <Td><Actor actor={po.created_by} /></Td>
                  <Td className="text-right tabular-nums">{po.lines.length}</Td>
                  <Td className="text-right tabular-nums">{number(po.units)}</Td>
                  <Td className="text-right font-medium tabular-nums">{money(po.total)}</Td>
                  <Td className="text-muted">{po.received_at ? `received ${shortDate(po.received_at)}` : po.expected_at ? shortDate(po.expected_at) : '—'}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {selected && <PODialog po={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

function PODialog({ po: initial, onClose }: { po: PurchaseOrder; onClose: () => void }) {
  const { can } = useAuth()
  const [po, setPo] = useState(initial)
  const change = useAction((status: POStatus) => post<PurchaseOrder>(`/api/purchase-orders/${po.id}/status`, { status }), {
    success: (r) => `${r.number} is now ${r.status}`,
    invalidate,
    onSuccess: setPo,
  })
  const next: { status: POStatus; label: string; icon: typeof Send; variant?: 'primary' | 'success' }[] =
    po.status === 'draft'
      ? [{ status: 'approved', label: 'Approve', icon: ThumbsUp }]
      : po.status === 'approved'
        ? [{ status: 'ordered', label: 'Mark as ordered', icon: Send }]
        : po.status === 'ordered'
          ? [{ status: 'received', label: 'Receive into stock', icon: PackageCheck, variant: 'success' }]
          : []

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      wide
      title={
        <span className="flex items-center gap-2">
          {po.number} <POStatusBadge status={po.status} />
        </span>
      }
      description={`${po.supplier?.name} → ${po.warehouse?.name} · created ${dateTime(po.created_at)}`}
      footer={
        <>
          <Button variant="ghost" onClick={() => window.print()}>
            <Printer className="size-4" /> Print
          </Button>
          {can('manager') && ['draft', 'approved', 'ordered'].includes(po.status) && (
            <Button variant="secondary" onClick={() => change.mutate('cancelled')} loading={change.isPending && change.variables === 'cancelled'}>
              <X className="size-4" /> Cancel PO
            </Button>
          )}
          {can('manager') &&
            next.map((n) => (
              <Button key={n.status} variant={n.variant ?? 'primary'} onClick={() => change.mutate(n.status)} loading={change.isPending && change.variables === n.status}>
                <n.icon className="size-4" /> {n.label}
              </Button>
            ))}
        </>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap gap-6 text-sm">
          <div>
            <div className="text-xs text-muted">Created by</div>
            <Actor actor={po.created_by} />
          </div>
          <div>
            <div className="text-xs text-muted">Expected</div>
            {po.expected_at ? shortDate(po.expected_at) : '—'}
          </div>
          <div>
            <div className="text-xs text-muted">Total</div>
            <span className="font-semibold">{money(po.total)}</span>
          </div>
        </div>
        {po.notes && <p className="rounded-lg bg-surface-2 px-3 py-2 text-sm text-muted">{po.notes}</p>}
        <Table>
          <thead>
            <tr>
              <Th>SKU</Th>
              <Th>Product</Th>
              <Th className="text-right">Qty</Th>
              <Th className="text-right">Unit cost</Th>
              <Th className="text-right">Total</Th>
            </tr>
          </thead>
          <tbody>
            {po.lines.map((l) => (
              <tr key={l.id}>
                <Td className="font-mono text-xs">{l.sku}</Td>
                <Td>{l.name}</Td>
                <Td className="text-right tabular-nums">{number(l.quantity)}</Td>
                <Td className="text-right tabular-nums">{money(l.unit_cost)}</Td>
                <Td className="text-right font-medium tabular-nums">{money(l.total)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </Dialog>
  )
}
