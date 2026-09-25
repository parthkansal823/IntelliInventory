import { ArrowDownUp, Download, PackagePlus, QrCode, Search, Sparkles, Upload } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { ForecastChart } from '@/components/charts'
import { Actor, StatusBadge, StockBar } from '@/components/domain'
import { ImportDialog, LabelDialog, ProductFormDialog, StockDialog } from '@/components/InventoryDialogs'
import { Badge, Button, Card, EmptyState, Input, PageHeader, Segmented, Select, Sheet, Skeleton, Table, Td, Th } from '@/components/ui'
import { keys, useAction, useCategories, useGstSettings, useProduct, useProducts } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { download, post } from '@/lib/api'
import type { ProductRow, StockStatus } from '@/lib/types'
import { cn, dateTime, money, number, shortDate, titleCase } from '@/lib/utils'

type SortKey = 'sku' | 'name' | 'on_hand' | 'days_of_cover' | 'avg_daily_demand' | 'stock_value' | 'status'

function SortTh({ k, sort, onSort, children, className }: { k: SortKey; sort: { key: SortKey }; onSort: (k: SortKey) => void; children: ReactNode; className?: string }) {
  return (
    <Th className={className}>
      <button onClick={() => onSort(k)} className={cn('inline-flex items-center gap-1 hover:text-fg', sort.key === k && 'text-fg')}>
        {children}
        <ArrowDownUp className="size-3 opacity-50" />
      </button>
    </Th>
  )
}
const STATUS_ORDER: Record<StockStatus, number> = { out: 0, critical: 1, low: 2, healthy: 3, overstock: 4 }

export default function Inventory() {
  const products = useProducts()
  const categories = useCategories()
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<'all' | 'attention' | StockStatus>('all')
  const [category, setCategory] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'status', dir: 1 })
  const [dialog, setDialog] = useState<null | 'new' | 'import'>(null)
  const selectedId = params.get('product') ? Number(params.get('product')) : null

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    let list = (products.data ?? []).filter((p) => p.is_active)
    if (q) list = list.filter((p) => `${p.sku} ${p.name} ${p.category} ${p.supplier}`.toLowerCase().includes(q))
    if (category) list = list.filter((p) => String(p.category_id) === category)
    if (status === 'attention') list = list.filter((p) => ['out', 'critical', 'low'].includes(p.status ?? ''))
    else if (status !== 'all') list = list.filter((p) => p.status === status)
    const val = (p: ProductRow) => (sort.key === 'status' ? STATUS_ORDER[p.status ?? 'healthy'] : (p[sort.key] ?? -1))
    return [...list].sort((a, b) => {
      const va = val(a)
      const vb = val(b)
      return (typeof va === 'string' ? va.localeCompare(String(vb)) : Number(va) - Number(vb)) * sort.dir
    })
  }, [products.data, query, status, category, sort])

  const toggleSort = (key: SortKey) => setSort((s) => ({ key, dir: s.key === key ? ((-s.dir) as 1 | -1) : 1 }))
  const attention = (products.data ?? []).filter((p) => ['out', 'critical', 'low'].includes(p.status ?? '')).length
  const gstOn = useGstSettings().data?.gst_enabled ?? true
  const missingGst = (products.data ?? []).filter((p) => p.is_active && p.gst_rate == null).length
  const fillGst = useAction(() => post<{ filled: number }>('/api/india/gst/autofill', {}), {
    success: (r) => `AI filled HSN + GST for ${r.filled} product(s) — marked "AI" for you to review`,
    invalidate: [keys.products, ['gst'], ['gst-settings']],
  })

  return (
    <div>
      <PageHeader
        title="Stock"
        description={`${rows.length} products · live stock, demand and when to reorder`}
        actions={
          <>
            {can('manager') && gstOn && missingGst > 0 && (
              <Button variant="secondary" onClick={() => fillGst.mutate(undefined)} loading={fillGst.isPending}>
                <Sparkles className="size-4" /> Fill GST with AI ({missingGst})
              </Button>
            )}
            <Button variant="secondary" onClick={() => download('/api/inventory/export.csv', 'inventory.csv')}>
              <Download className="size-4" /> Export
            </Button>
            {can('manager') && (
              <>
                <Button variant="secondary" onClick={() => setDialog('import')}>
                  <Upload className="size-4" /> Import CSV
                </Button>
                <Button onClick={() => setDialog('new')}>
                  <PackagePlus className="size-4" /> Add product
                </Button>
              </>
            )}
          </>
        }
      />

      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-border p-3">
          <div className="relative min-w-56 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search SKU, name, supplier…" className="pl-9" />
          </div>
          <Select value={category} onChange={(e) => setCategory(e.target.value)} className="w-44">
            <option value="">All categories</option>
            {categories.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Segmented
            size="sm"
            value={status}
            onChange={setStatus}
            options={[
              { value: 'all', label: 'All' },
              { value: 'attention', label: <>Needs attention <Badge tone="warning">{attention}</Badge></> },
              { value: 'overstock', label: 'Overstock' },
            ]}
          />
        </div>
        {products.isLoading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : !rows.length ? (
          <EmptyState title="No products match" description="Try a different search or filter." />
        ) : (
          <Table>
            <thead>
              <tr>
                <SortTh sort={sort} onSort={toggleSort} k="sku">SKU</SortTh>
                <SortTh sort={sort} onSort={toggleSort} k="name">Product</SortTh>
                <SortTh sort={sort} onSort={toggleSort} k="on_hand">On hand · ROP</SortTh>
                <SortTh sort={sort} onSort={toggleSort} k="status">Status</SortTh>
                <SortTh sort={sort} onSort={toggleSort} k="days_of_cover" className="text-right">Cover</SortTh>
                <SortTh sort={sort} onSort={toggleSort} k="avg_daily_demand" className="text-right">Demand/day</SortTh>
                <Th>ABC</Th>
                <SortTh sort={sort} onSort={toggleSort} k="stock_value" className="text-right">Value</SortTh>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id} onClick={() => setParams({ product: String(p.id) })} className="cursor-pointer transition hover:bg-surface-2/60">
                  <Td className="font-mono text-xs text-muted">{p.sku}</Td>
                  <Td>
                    <div className="font-medium">{p.name}</div>
                    <div className="text-xs text-subtle">{p.category} · {p.supplier}</div>
                  </Td>
                  <Td>
                    <StockBar onHand={p.on_hand} reorderPoint={p.reorder_point} status={p.status} />
                  </Td>
                  <Td>
                    <div className="flex items-center gap-1.5">
                      <StatusBadge status={p.status} />
                      {!!p.on_order && <Badge tone="info">+{p.on_order}</Badge>}
                    </div>
                  </Td>
                  <Td className="text-right tabular-nums">{p.days_of_cover == null ? '—' : `${p.days_of_cover}d`}</Td>
                  <Td className="text-right tabular-nums">{p.avg_daily_demand}</Td>
                  <Td>
                    <Badge tone={p.abc_class === 'A' ? 'brand' : 'neutral'}>{p.abc_class}</Badge>
                  </Td>
                  <Td className="text-right tabular-nums">{money(p.stock_value)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <ProductDrawer id={selectedId} onClose={() => setParams({})} />
      <ProductFormDialog open={dialog === 'new'} onOpenChange={(o) => setDialog(o ? 'new' : null)} />
      <ImportDialog open={dialog === 'import'} onOpenChange={(o) => setDialog(o ? 'import' : null)} />
    </div>
  )
}

function ProductDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { data: p, isLoading } = useProduct(id)
  const gstOn = useGstSettings().data?.gst_enabled ?? true
  const { can } = useAuth()
  const navigate = useNavigate()
  const [dialog, setDialog] = useState<null | 'adjust' | 'transfer' | 'label' | 'edit'>(null)
  const [tab, setTab] = useState<'forecast' | 'movements'>('forecast')

  return (
    <Sheet
      open={id != null}
      onOpenChange={(o) => !o && onClose()}
      title={p ? p.name : 'Loading…'}
      description={p ? `${p.sku} · ${p.category} · ${p.supplier}` : undefined}
      headerAction={p && <StatusBadge status={p.status} />}
    >
      {isLoading || !p ? (
        <div className="space-y-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-64" />
        </div>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap gap-2">
            {can('staff') && (
              <>
                <Button size="sm" onClick={() => setDialog('adjust')}>Adjust stock</Button>
                <Button size="sm" variant="secondary" onClick={() => setDialog('transfer')}>Transfer</Button>
              </>
            )}
            <Button size="sm" variant="secondary" onClick={() => setDialog('label')}>
              <QrCode className="size-3.5" /> Label
            </Button>
            {can('manager') && (
              <Button size="sm" variant="secondary" onClick={() => setDialog('edit')}>Edit</Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => navigate(`/copilot?q=${encodeURIComponent(`Investigate ${p.sku}: stock, forecast, anomalies and the best next action`)}`)}>
              <Sparkles className="size-3.5" /> Ask Copilot
            </Button>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ['On hand', number(p.on_hand)],
              ['On order', number(p.on_order)],
              ['Days of cover', p.days_of_cover == null ? '—' : `${p.days_of_cover}d`],
              ['Stockout ≈', p.stockout_date ? shortDate(p.stockout_date) : '—'],
              ['Safety stock', number(p.safety_stock)],
              ['Reorder point', number(p.reorder_point)],
              ['EOQ', number(p.eoq)],
              ['Lead time', `${p.lead_time_days}d`],
              ...(gstOn
                ? [
                    ['GST', p.gst_rate == null ? 'AI will fill' : `${p.gst_rate}%${p.gst_source === 'ai' ? ' · AI (check)' : ''}`],
                    ['HSN', p.hsn_code ?? '—'],
                    ['Price incl. GST', money(p.price_incl_gst)],
                    ['Margin', p.unit_price ? `${Math.round(((p.unit_price - p.unit_cost) / p.unit_price) * 100)}%` : '—'],
                  ]
                : []),
            ].map(([label, value]) => (
              <Card key={label} className="p-3">
                <div className="text-xs text-muted">{label}</div>
                <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
              </Card>
            ))}
          </div>

          {!!p.suggested_order_qty && (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-brand/25 bg-brand-soft px-4 py-3 text-sm">
              <span>
                <b>Reorder {number(p.suggested_order_qty)} units</b> ({money(p.suggested_order_qty * p.unit_cost)}) — inventory position is at or below the reorder point.
              </span>
            </div>
          )}

          <Card>
            <div className="flex items-center justify-between border-b border-border px-4 py-2">
              <Segmented size="sm" value={tab} onChange={setTab} options={[{ value: 'forecast', label: 'Demand forecast' }, { value: 'movements', label: 'Movements' }]} />
              {tab === 'forecast' && p.forecast && (
                <span className="text-xs text-muted">
                  {p.forecast.method} · MAPE {p.forecast.mape ?? '—'}% · {p.forecast.total_forecast} units / 30d
                </span>
              )}
            </div>
            <div className="p-4">
              {tab === 'forecast' ? (
                p.forecast ? <ForecastChart data={p.forecast} /> : <EmptyState title="No demand history" />
              ) : (
                <ul className="max-h-80 divide-y divide-border overflow-y-auto text-sm">
                  {p.movements.map((m) => (
                    <li key={m.id} className="flex items-center justify-between gap-3 py-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{titleCase(m.type)}</span>
                          <span className="text-xs text-subtle">{m.warehouse}</span>
                          {m.reference && <span className="font-mono text-xs text-subtle">{m.reference}</span>}
                        </div>
                        <div className="truncate text-xs text-muted">{dateTime(m.created_at)} {m.note && `· ${m.note}`}</div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Actor actor={m.actor} />
                        <span className={cn('w-14 text-right font-medium tabular-nums', m.quantity > 0 ? 'text-good' : 'text-fg')}>
                          {m.quantity > 0 ? '+' : ''}
                          {m.quantity}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Card>

          <Card>
            <div className="border-b border-border px-4 py-2.5 text-sm font-medium">Stock by warehouse</div>
            <ul className="divide-y divide-border">
              {p.warehouses.map((w) => (
                <li key={w.warehouse_id} className="flex items-center justify-between px-4 py-2.5 text-sm">
                  <span>
                    {w.name} <span className="ml-1 font-mono text-xs text-subtle">{w.code}</span>
                  </span>
                  <span className="font-medium tabular-nums">{number(w.quantity)}</span>
                </li>
              ))}
              {!p.warehouses.length && <li className="px-4 py-3 text-sm text-muted">No stock in any warehouse.</li>}
            </ul>
          </Card>

          <StockDialog product={p} mode={dialog === 'transfer' ? 'transfer' : 'adjust'} open={dialog === 'adjust' || dialog === 'transfer'} onOpenChange={(o) => !o && setDialog(null)} />
          <LabelDialog product={p} open={dialog === 'label'} onOpenChange={(o) => !o && setDialog(null)} />
          <ProductFormDialog product={p} open={dialog === 'edit'} onOpenChange={(o) => !o && setDialog(null)} />
        </div>
      )}
    </Sheet>
  )
}
