import { MessageCircle, PackageCheck, Printer, Send, ShoppingCart, Sparkles, ThumbsUp, Truck, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Actor, POStatusBadge } from '@/components/domain'
import { Badge, Button, Card, Dialog, EmptyState, PageHeader, Skeleton, Table, Tabs, TabsList, TabsTrigger, Td, Th } from '@/components/ui'
import { keys, useAction, useBillingProfile, usePOStats, usePurchaseOrders } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { post } from '@/lib/api'
import { qrDataUrl } from '@/lib/billing'
import { whatsappLink } from '@/lib/speech'
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
                <Th className="text-right">Total (incl. GST)</Th>
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
                  <Td className="text-right font-medium tabular-nums">{money(po.grand_total)}</Td>
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

function poWhatsApp(po: PurchaseOrder, shop: string): string {
  const lines = po.lines.map((l) => `• ${l.name} (${l.sku}) × ${l.quantity}`).join('\n')
  return `Namaste 🙏\n*Purchase order ${po.number}* from ${shop}\n\nPlease supply:\n${lines}\n\nValue: *${money(po.grand_total)}*${po.tax.enabled ? ' (incl. GST)' : ''}\nDeliver to: ${po.warehouse?.name ?? '—'}${po.expected_at ? ` by ${shortDate(po.expected_at)}` : ''}\n\nPlease confirm. Dhanyavaad!`
}

function PODialog({ po: initial, onClose }: { po: PurchaseOrder; onClose: () => void }) {
  const { can } = useAuth()
  const [po, setPo] = useState(initial)
  const shop = useBillingProfile().data?.name ?? 'our shop'
  const [upiQr, setUpiQr] = useState<{ link: string; url: string } | null>(null)
  useEffect(() => {
    let alive = true
    const link = po.upi_link
    if (link) void qrDataUrl(link, 140).then((url) => alive && setUpiQr({ link, url }))
    return () => {
      alive = false
    }
  }, [po.upi_link])
  const qr = po.upi_link && upiQr?.link === po.upi_link ? upiQr.url : null
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
          <a href={whatsappLink(poWhatsApp(po, shop), po.supplier?.phone)} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-2 rounded-lg px-3.5 text-sm font-medium text-muted hover:bg-surface-2 hover:text-fg">
            <MessageCircle className="size-4" /> Send on WhatsApp
          </a>
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
            <div className="text-xs text-muted">Total{po.tax.enabled ? ' (incl. GST)' : ''}</div>
            <span className="font-semibold">{money(po.grand_total)}</span>
          </div>
          {po.supplier?.gstin && (
            <div>
              <div className="text-xs text-muted">Supplier GSTIN</div>
              <span className="font-mono text-xs">{po.supplier.gstin}</span>
            </div>
          )}
        </div>
        {po.tax.eway_bill_required && (
          <div className="flex items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
            <Truck className="size-4 shrink-0" /> Value is above ₹50,000 — the supplier must generate an <b>e-way bill</b> before dispatch.
          </div>
        )}
        {po.notes && <p className="rounded-lg bg-surface-2 px-3 py-2 text-sm text-muted">{po.notes}</p>}
        <Table>
          <thead>
            <tr>
              <Th>SKU</Th>
              <Th>Product</Th>
              <Th className="text-right">Qty</Th>
              <Th className="text-right">Unit cost</Th>
              {po.tax.enabled && <Th className="text-right">GST</Th>}
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
                {po.tax.enabled && <Td className="text-right tabular-nums">{l.gst_rate ?? 0}%</Td>}
                <Td className="text-right font-medium tabular-nums">{money(l.total)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <div className="flex flex-wrap items-end justify-between gap-4">
          {qr ? (
            <div className="flex items-center gap-3">
              <img src={qr} alt="UPI QR" className="size-24 rounded-lg border border-border" />
              <div className="text-xs text-muted">Pay {po.supplier?.name} by UPI<div className="font-mono">{po.supplier?.upi_id}</div></div>
            </div>
          ) : <span />}
          {po.tax.enabled && (
            <div className="min-w-60 space-y-1 text-sm">
              <div className="flex justify-between text-muted"><span>Taxable value</span><span className="tabular-nums">{money(po.tax.taxable)}</span></div>
              {po.tax.interstate ? (
                <div className="flex justify-between text-muted"><span>IGST <Badge tone="info">inter-state</Badge></span><span className="tabular-nums">{money(po.tax.igst)}</span></div>
              ) : (
                <>
                  <div className="flex justify-between text-muted"><span>CGST</span><span className="tabular-nums">{money(po.tax.cgst)}</span></div>
                  <div className="flex justify-between text-muted"><span>SGST</span><span className="tabular-nums">{money(po.tax.sgst)}</span></div>
                </>
              )}
              <div className="flex justify-between border-t border-border pt-1 font-semibold"><span>Grand total</span><span className="tabular-nums">{money(po.grand_total)}</span></div>
            </div>
          )}
        </div>
      </div>
    </Dialog>
  )
}
