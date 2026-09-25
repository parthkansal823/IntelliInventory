import QRCode from 'qrcode'
import { Printer, Sparkles } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { keys, useAction, useCategories, useGstSettings, useSuppliers, useWarehouses } from '@/hooks/queries'
import { patch, post } from '@/lib/api'
import type { GstSuggestion, ProductDetail, ProductRow } from '@/lib/types'
import { money } from '@/lib/utils'
import { Badge, Button, Dialog, Field, Input, Segmented, Select, Textarea } from './ui'

const refresh = [keys.products, ['products'], keys.dashboard, keys.alerts, keys.reorder, ['health']]

export function StockDialog({ product, mode, open, onOpenChange }: { product: ProductDetail; mode: 'adjust' | 'transfer'; open: boolean; onOpenChange: (o: boolean) => void }) {
  const warehouses = useWarehouses()
  const [kind, setKind] = useState<'receipt' | 'sale' | 'adjustment' | 'return'>('adjustment')
  const [qty, setQty] = useState(1)
  const [reason, setReason] = useState('')
  const [from, setFrom] = useState<number | ''>('')
  const [to, setTo] = useState<number | ''>('')

  useEffect(() => {
    if (open && warehouses.data?.length) {
      const first = product.warehouses[0]?.warehouse_id ?? warehouses.data[0].id
      setFrom(first)
      setTo(warehouses.data.find((w) => w.id !== first)?.id ?? '')
    }
  }, [open, warehouses.data, product.warehouses])

  const adjust = useAction(
    () => post('/api/inventory/adjust', { product_id: product.id, quantity: qty, type: kind, reason: reason || undefined, warehouse_id: from || undefined }),
    { success: 'Stock updated', invalidate: refresh, onSuccess: () => onOpenChange(false) },
  )
  const transfer = useAction(
    () => post('/api/inventory/transfer', { product_id: product.id, quantity: qty, from_warehouse_id: from, to_warehouse_id: to }),
    { success: 'Transfer completed', invalidate: refresh, onSuccess: () => onOpenChange(false) },
  )
  const submit = (e: FormEvent) => {
    e.preventDefault()
    ;(mode === 'transfer' ? transfer : adjust).mutate(undefined)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={mode === 'transfer' ? 'Transfer stock' : 'Record stock movement'}
      description={`${product.name} · ${product.on_hand} on hand`}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" form="stock-form" loading={adjust.isPending || transfer.isPending}>
            {mode === 'transfer' ? 'Transfer' : 'Save'}
          </Button>
        </>
      }
    >
      <form id="stock-form" onSubmit={submit} className="space-y-4">
        {mode === 'adjust' && (
          <Segmented
            value={kind}
            onChange={setKind}
            options={[
              { value: 'adjustment', label: 'Adjust ±' },
              { value: 'receipt', label: 'Receive' },
              { value: 'sale', label: 'Sell' },
              { value: 'return', label: 'Return' },
            ]}
          />
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label={mode === 'transfer' ? 'From' : 'Warehouse'}>
            <Select value={from} onChange={(e) => setFrom(Number(e.target.value))}>
              {warehouses.data?.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.code} — {w.name} ({product.warehouses.find((x) => x.warehouse_id === w.id)?.quantity ?? 0})
                </option>
              ))}
            </Select>
          </Field>
          {mode === 'transfer' ? (
            <Field label="To">
              <Select value={to} onChange={(e) => setTo(Number(e.target.value))}>
                {warehouses.data?.filter((w) => w.id !== from).map((w) => (
                  <option key={w.id} value={w.id}>{w.code} — {w.name}</option>
                ))}
              </Select>
            </Field>
          ) : (
            <Field label={kind === 'adjustment' ? 'Quantity (negative to remove)' : 'Quantity'}>
              <Input type="number" value={qty} onChange={(e) => setQty(Number(e.target.value))} required />
            </Field>
          )}
        </div>
        {mode === 'transfer' && (
          <Field label="Quantity">
            <Input type="number" min={1} value={qty} onChange={(e) => setQty(Number(e.target.value))} required />
          </Field>
        )}
        {mode === 'adjust' && (
          <Field label="Reason" hint="Recorded in the audit trail">
            <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. damaged in transit" />
          </Field>
        )}
      </form>
    </Dialog>
  )
}

export function ProductFormDialog({ product, open, onOpenChange }: { product?: ProductRow; open: boolean; onOpenChange: (o: boolean) => void }) {
  const categories = useCategories()
  const suppliers = useSuppliers()
  const warehouses = useWarehouses()
  const gst = useGstSettings().data
  const empty = { sku: '', name: '', description: '', category_id: '', supplier_id: '', unit_cost: 0, unit_price: 0, min_order_qty: 1, reorder_point: '', safety_stock: '', initial_qty: 0, warehouse_id: '', hsn_code: '', gst_rate: '' }
  const [form, setForm] = useState<Record<string, string | number>>(empty)
  const [gstTouched, setGstTouched] = useState(false)
  const [hint, setHint] = useState<GstSuggestion | null>(null)

  useEffect(() => {
    if (!open) return
    setForm(
      product
        ? {
            ...empty,
            sku: product.sku,
            name: product.name,
            description: product.description ?? '',
            category_id: product.category_id ?? '',
            supplier_id: product.supplier_id ?? '',
            unit_cost: product.unit_cost,
            unit_price: product.unit_price,
            min_order_qty: product.min_order_qty,
            reorder_point: product.manual_reorder_point ?? '',
            safety_stock: product.manual_safety_stock ?? '',
            hsn_code: product.hsn_code ?? '',
            gst_rate: product.gst_rate ?? '',
          }
        : empty,
    )
    setGstTouched(false)
    setHint(null)
  }, [open, product])

  const num = (v: string | number) => (v === '' ? null : Number(v))
  const body = () => ({
    name: form.name,
    description: form.description || null,
    category_id: num(form.category_id),
    supplier_id: num(form.supplier_id),
    unit_cost: Number(form.unit_cost),
    unit_price: Number(form.unit_price),
    min_order_qty: Number(form.min_order_qty) || 1,
    reorder_point: num(form.reorder_point),
    safety_stock: num(form.safety_stock),
    // GST is optional: only sent when a person set it (the AI fills blanks later and never overrides you)
    ...(gstTouched ? { hsn_code: form.hsn_code || null, gst_rate: num(form.gst_rate) } : {}),
  })
  const suggest = useAction(
    () => post<GstSuggestion>('/api/india/gst/suggest', { name: form.name, category: categories.data?.find((c) => c.id === Number(form.category_id))?.name ?? null }),
    {
      onSuccess: (r) => {
        setHint(r)
        setGstTouched(true)
        setForm((f) => ({ ...f, gst_rate: r.gst_rate, hsn_code: r.hsn_code ?? f.hsn_code }))
      },
    },
  )
  const save = useAction(
    () =>
      product
        ? patch(`/api/products/${product.id}`, body())
        : post('/api/products', { ...body(), sku: form.sku, initial_qty: Number(form.initial_qty) || 0, warehouse_id: num(form.warehouse_id) }),
    { success: product ? 'Product updated' : 'Product created', invalidate: refresh, onSuccess: () => onOpenChange(false) },
  )
  const set = (k: string) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const setGst = (k: string) => (e: { target: { value: string } }) => {
    setGstTouched(true)
    set(k)(e)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      wide
      title={product ? `Edit ${product.sku}` : 'Add product'}
      description="Leave reorder point / safety stock empty to let the AI compute them from demand."
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button type="submit" form="product-form" loading={save.isPending}>Save</Button>
        </>
      }
    >
      <form id="product-form" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined) }} className="grid gap-4 sm:grid-cols-2">
        <Field label="SKU"><Input value={form.sku} onChange={set('sku')} disabled={!!product} required placeholder="ELC-2001" /></Field>
        <Field label="Name"><Input value={form.name} onChange={set('name')} required /></Field>
        <Field label="Category">
          <Select value={form.category_id} onChange={set('category_id')}>
            <option value="">—</option>
            {categories.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
        </Field>
        <Field label="Supplier">
          <Select value={form.supplier_id} onChange={set('supplier_id')}>
            <option value="">—</option>
            {suppliers.data?.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.lead_time_days}d)</option>)}
          </Select>
        </Field>
        <Field label="Unit cost (₹)"><Input type="number" step="0.01" min={0} value={form.unit_cost} onChange={set('unit_cost')} /></Field>
        <Field label="Selling price (₹, before GST)"><Input type="number" step="0.01" min={0} value={form.unit_price} onChange={set('unit_price')} /></Field>
        {gst?.gst_enabled !== false && (
          <div className="grid gap-3 rounded-lg border border-dashed border-border p-3 sm:col-span-2 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <Field label="GST rate (optional)" hint={product?.gst_source === 'ai' && !gstTouched ? 'Filled by AI — please check' : 'Leave blank: AI fills it from the name'}>
              <Select value={form.gst_rate} onChange={setGst('gst_rate')}>
                <option value="">Let AI fill later</option>
                {(gst?.slabs ?? [0, 5, 18, 40]).map((r) => <option key={r} value={r}>{r}%</option>)}
              </Select>
            </Field>
            <Field label="HSN code (optional)"><Input value={form.hsn_code} onChange={setGst('hsn_code')} placeholder="e.g. 1006" className="font-mono" /></Field>
            <Button type="button" variant="secondary" disabled={!String(form.name).trim()} loading={suggest.isPending} onClick={() => suggest.mutate(undefined)}>
              <Sparkles className="size-4" /> Suggest with AI
            </Button>
            {hint && <p className="text-xs text-muted sm:col-span-3">✨ {hint.reason} <Badge tone={hint.confidence === 'high' ? 'good' : hint.confidence === 'medium' ? 'info' : 'warning'}>{hint.confidence} confidence</Badge> — confirm with your CA.</p>}
          </div>
        )}
        <Field label="Min. order qty"><Input type="number" min={1} value={form.min_order_qty} onChange={set('min_order_qty')} /></Field>
        <Field label="Reorder point" hint="auto if empty"><Input type="number" min={0} value={form.reorder_point} onChange={set('reorder_point')} /></Field>
        <Field label="Safety stock" hint="auto if empty"><Input type="number" min={0} value={form.safety_stock} onChange={set('safety_stock')} /></Field>
        {!product && (
          <>
            <Field label="Initial quantity"><Input type="number" min={0} value={form.initial_qty} onChange={set('initial_qty')} /></Field>
            <Field label="Initial warehouse">
              <Select value={form.warehouse_id} onChange={set('warehouse_id')}>
                <option value="">Default</option>
                {warehouses.data?.map((w) => <option key={w.id} value={w.id}>{w.code} — {w.name}</option>)}
              </Select>
            </Field>
          </>
        )}
        <Field label="Description" className="sm:col-span-2"><Textarea rows={2} value={form.description} onChange={set('description')} /></Field>
      </form>
    </Dialog>
  )
}

interface ImportResult { ok: boolean; error?: string; committed: boolean; summary: { create: number; update: number; error: number }; rows: { line: number; sku: string; name: string; action: string; errors: string[] }[] }

export function ImportDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [csv, setCsv] = useState('')
  const [preview, setPreview] = useState<ImportResult | null>(null)
  const dryRun = useAction(() => post<ImportResult>('/api/inventory/import', { csv, commit: false }), { onSuccess: setPreview })
  const commit = useAction(() => post<ImportResult>('/api/inventory/import', { csv, commit: true }), {
    success: (r) => `Imported: ${r.summary.create} created, ${r.summary.update} updated`,
    invalidate: refresh,
    onSuccess: () => { setPreview(null); setCsv(''); onOpenChange(false) },
  })
  const template = 'sku,name,category,supplier,unit_cost,unit_price,min_order_qty,reorder_point,safety_stock,initial_qty,warehouse\nNEW-0001,Sample Product,Accessories,Pacific Components,4.5,12.99,10,,,100,MAIN'

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      wide
      title="Import products from CSV"
      description="Preview validates every row before anything is written."
      footer={
        <>
          <Button variant="secondary" onClick={() => dryRun.mutate(undefined)} loading={dryRun.isPending} disabled={!csv.trim()}>Preview</Button>
          <Button onClick={() => commit.mutate(undefined)} loading={commit.isPending} disabled={!preview?.ok}>Import</Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Input type="file" accept=".csv,text/csv" onChange={async (e) => { const f = e.target.files?.[0]; if (f) { setCsv(await f.text()); setPreview(null) } }} />
          <Button variant="ghost" size="sm" onClick={() => { setCsv(template); setPreview(null) }}>Use template</Button>
        </div>
        <Textarea rows={6} value={csv} onChange={(e) => { setCsv(e.target.value); setPreview(null) }} placeholder="…or paste CSV here" className="font-mono text-xs" />
        {preview && (
          <div className="rounded-lg border border-border">
            <div className="flex gap-2 border-b border-border px-3 py-2 text-xs">
              {preview.error ? <span className="text-critical">{preview.error}</span> : (
                <>
                  <Badge tone="good">{preview.summary.create} new</Badge>
                  <Badge tone="info">{preview.summary.update} update</Badge>
                  <Badge tone={preview.summary.error ? 'critical' : 'neutral'}>{preview.summary.error} errors</Badge>
                </>
              )}
            </div>
            <ul className="max-h-48 divide-y divide-border overflow-y-auto text-xs">
              {preview.rows.map((r) => (
                <li key={r.line} className="flex justify-between gap-3 px-3 py-1.5">
                  <span><span className="text-subtle">L{r.line}</span> <span className="font-mono">{r.sku}</span> {r.name}</span>
                  <span className={r.errors.length ? 'text-critical' : 'text-muted'}>{r.errors.join('; ') || r.action}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Dialog>
  )
}

export function LabelDialog({ product, open, onOpenChange }: { product: ProductRow; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [src, setSrc] = useState('')
  useEffect(() => {
    if (open) QRCode.toDataURL(`ii:${product.sku}`, { margin: 1, width: 320 }).then(setSrc)
  }, [open, product.sku])

  const print = () => {
    const w = window.open('', '_blank', 'width=420,height=520')
    if (!w) return
    w.document.write(`<html><head><title>${product.sku}</title><style>body{font-family:system-ui;text-align:center;padding:24px}img{width:220px}h2{margin:8px 0 2px;font-size:18px}p{margin:0;color:#555}</style></head><body><img src="${src}"/><h2>${product.name}</h2><p>${product.sku} · ${money(product.unit_price)}</p><script>window.onload=()=>{window.print()}</script></body></html>`)
    w.document.close()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Product label" description="Scan it on the Scan page to receive, sell or count this item." footer={<Button onClick={print}><Printer className="size-4" /> Print label</Button>}>
      <div className="flex flex-col items-center gap-2 py-2">
        {src && <img src={src} alt={`QR code for ${product.sku}`} className="size-48 rounded-lg border border-border bg-white p-2" />}
        <div className="text-base font-semibold">{product.name}</div>
        <div className="font-mono text-sm text-muted">{product.sku} · {money(product.unit_price)}</div>
      </div>
    </Dialog>
  )
}
