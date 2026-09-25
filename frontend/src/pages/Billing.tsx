/** Billing: make a bill in 3 steps (items → customer → payment), invoices list and the udhaar khata. */
import { BookUser, Camera, CameraOff, Download, IndianRupee, MessageCircle, Minus, Plus, Printer, QrCode, ReceiptIndianRupee, Search, Trash2, Wallet, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, Field, Input, PageHeader, Segmented, Select, Skeleton, Switch, Table, Tabs, TabsContent, TabsList, TabsTrigger, Td, Th, type Tone } from '@/components/ui'
import { useAction, useBillingProfile, useBillingSummary, useCustomers, useDues, useGstSettings, useInvoice, useInvoices, useProducts } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { useBarcodeScanner } from '@/hooks/useBarcodeScanner'
import { download, post } from '@/lib/api'
import { duesReminder, invoiceWhatsApp, previewBill, printInvoice, qrDataUrl, upiLink, type DraftLine } from '@/lib/billing'
import { whatsappLink } from '@/lib/speech'
import type { CustomerDue, InvoiceDetail, InvoiceStatus, PaymentMode, ProductRow } from '@/lib/types'
import { cn, dateTime, money, number, shortDate } from '@/lib/utils'

const INVALIDATE = [['invoices'], ['invoice'], ['billing'], ['customers'], ['products'], ['dashboard'], ['gst']]

const MODE_LABEL: Record<string, string> = { cash: 'Cash', upi: 'UPI', card: 'Card', bank: 'Bank', credit: 'Udhaar', split: 'Split' }
const STATUS: Record<InvoiceStatus, { tone: Tone; label: string }> = {
  paid: { tone: 'good', label: 'Paid' },
  partial: { tone: 'warning', label: 'Part paid' },
  unpaid: { tone: 'critical', label: 'Udhaar' },
  cancelled: { tone: 'neutral', label: 'Cancelled' },
}

export default function Billing() {
  const [params, setParams] = useSearchParams()
  const [openId, setOpenId] = useState<number | null>(null)
  return (
    <div>
      <PageHeader title="Billing" description="Make a bill in 3 steps, share it on WhatsApp, collect by UPI and keep track of udhaar." />
      <SummaryStrip />
      <Tabs value={params.get('tab') ?? 'new'} onValueChange={(tab) => setParams({ tab }, { replace: true })}>
        <TabsList>
          <TabsTrigger value="new"><ReceiptIndianRupee className="size-4" /> New bill</TabsTrigger>
          <TabsTrigger value="invoices"><IndianRupee className="size-4" /> All bills</TabsTrigger>
          <TabsTrigger value="khata"><BookUser className="size-4" /> Khata (udhaar)</TabsTrigger>
        </TabsList>
        <TabsContent value="new"><NewBill onSaved={setOpenId} /></TabsContent>
        <TabsContent value="invoices"><InvoiceList onOpen={setOpenId} /></TabsContent>
        <TabsContent value="khata"><Khata onOpen={setOpenId} /></TabsContent>
      </Tabs>
      {openId && <InvoiceDialog id={openId} onClose={() => setOpenId(null)} />}
    </div>
  )
}

function SummaryStrip() {
  const s = useBillingSummary(7).data
  const items = [
    { label: "Today's sales", value: money(s?.today.sales), hint: `${s?.today.bills ?? 0} bills` },
    { label: 'Last 7 days', value: money(s?.period.sales), hint: `${s?.period.bills ?? 0} bills · avg ${money(s?.period.avg_bill)}` },
    { label: 'Udhaar to collect', value: money(s?.outstanding), hint: `${s?.customers_with_dues ?? 0} customer${s?.customers_with_dues === 1 ? '' : 's'}`, tone: s?.outstanding ? 'text-critical' : '' },
    { label: 'Collected by UPI (7d)', value: money(s?.collected_by_mode.upi ?? 0), hint: `cash ${money(s?.collected_by_mode.cash ?? 0)}` },
  ]
  return (
    <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
      {items.map((i) => (
        <Card key={i.label} className="p-4">
          <div className="text-xs text-muted">{i.label}</div>
          <div className={cn('mt-1 text-xl font-semibold tabular-nums', i.tone)}>{s ? i.value : '…'}</div>
          <div className="mt-0.5 text-xs text-subtle">{i.hint}</div>
        </Card>
      ))}
    </div>
  )
}

// --- New bill ------------------------------------------------------------------------------

type Mode = PaymentMode | 'split'
const onlyDigits = (s: string | null | undefined) => (s ?? '').replace(/\D/g, '').slice(-10)
const paise = (n: number) => Math.round((n + Number.EPSILON) * 100) / 100

function NewBill({ onSaved }: { onSaved: (id: number) => void }) {
  const products = useProducts()
  const customers = useCustomers()
  const profile = useBillingProfile().data
  const settings = useGstSettings().data
  const { can } = useAuth()
  const gstOn = settings?.gst_enabled ?? true
  const [lines, setLines] = useState<DraftLine[]>([])
  const [inclusive, setInclusive] = useState(true)
  const [query, setQuery] = useState('')
  const [customer, setCustomer] = useState({ name: '', phone: '', state: '', gstin: '', address: '' })
  const [showCustomer, setShowCustomer] = useState(false)
  const [mode, setMode] = useState<Mode>('cash')
  const [cashGiven, setCashGiven] = useState('')
  const [utr, setUtr] = useState('')
  const [split, setSplit] = useState({ cash: '', upi: '' })
  const [qr, setQr] = useState<string | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    return (products.data ?? []).filter((p) => p.is_active && (p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q))).slice(0, 8)
  }, [query, products.data])

  const findCustomer = (phone: string) => {
    const digits = onlyDigits(phone)
    return digits.length >= 10 ? customers.data?.find((c) => onlyDigits(c.phone) === digits) : undefined
  }
  const known = findCustomer(customer.phone)
  const setPhone = (phone: string) => {
    const match = findCustomer(phone)
    setCustomer((c) => (match ? { ...c, phone, name: c.name || match.name, state: c.state || match.state || '', gstin: c.gstin || match.gstin || '', address: c.address || match.address || '' } : { ...c, phone }))
  }

  const shopState = profile?.state || ''
  const place = customer.state || shopState
  const exportSale = place === 'Outside India'
  const interstate = exportSale || (!!customer.state && !!shopState && customer.state !== shopState)
  const bill = previewBill(lines, { inclusive, interstate, exportSale, gstOn })
  const hasCustomer = !!(customer.name.trim() || customer.phone.trim())
  const splitPaid = (Number(split.cash) || 0) + (Number(split.upi) || 0)

  const add = (p: ProductRow) => {
    const rate = p.gst_rate ?? 0
    setLines((ls) => {
      const found = ls.find((l) => l.product_id === p.id)
      if (found) return ls.map((l) => (l.product_id === p.id ? { ...l, quantity: l.quantity + 1 } : l))
      // MRP-style prices are whole rupees; B2B (GST-exclusive) prices keep paise
      const price = inclusive && gstOn ? Math.round(p.unit_price * (1 + rate / 100)) : p.unit_price
      return [...ls, { product_id: p.id, sku: p.sku, name: p.name, quantity: 1, unit_price: price, discount_pct: 0, gst_rate: rate, stock: p.on_hand ?? 0 }]
    })
    setQuery('')
    searchRef.current?.focus()
  }
  const addByCode = (code: string) => {
    const p = products.data?.find((x) => x.sku.toLowerCase() === code.trim().toLowerCase())
    if (p) add(p)
    else toast.error(`No product with code ${code}`)
  }
  const { videoRef, active: scanning, start: startScan, stop: stopScan } = useBarcodeScanner(addByCode)
  const update = (id: number, patch: Partial<DraftLine>) => setLines((ls) => ls.map((l) => (l.product_id === id ? { ...l, ...patch } : l)))
  const toggleInclusive = (v: boolean) => {
    setInclusive(v)
    setLines((ls) => ls.map((l) => ({ ...l, unit_price: paise(v ? l.unit_price * (1 + l.gst_rate / 100) : l.unit_price / (1 + l.gst_rate / 100)) })))
  }
  const reset = () => {
    setLines([])
    setCustomer({ name: '', phone: '', state: '', gstin: '', address: '' })
    setShowCustomer(false)
    setMode('cash')
    setCashGiven('')
    setUtr('')
    setSplit({ cash: '', upi: '' })
    setQr(null)
  }

  const save = useAction(
    () =>
      post<InvoiceDetail>('/api/invoices', {
        items: lines.map((l) => ({ product_id: l.product_id, quantity: l.quantity, unit_price: l.unit_price, discount_pct: l.discount_pct })),
        customer: hasCustomer ? customer : null,
        prices_include_gst: inclusive && gstOn,
        payment_mode: mode === 'split' ? 'cash' : mode,
        payments:
          mode === 'split'
            ? [{ mode: 'cash', amount: Number(split.cash) || 0 }, { mode: 'upi', amount: Number(split.upi) || 0 }]
            : mode === 'upi' && utr
              ? [{ mode: 'upi', amount: bill.total, reference: utr }]
              : null,
      }),
    {
      success: (r) => `${r.number} saved · ${money(r.total)}${r.balance ? ` · ${money(r.balance)} on khata` : ''}`,
      invalidate: INVALIDATE,
      onSuccess: (r) => {
        reset()
        onSaved(r.id)
      },
    },
  )

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'F2') {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const showQr = async () => setQr(profile?.upi_id ? await qrDataUrl(upiLink(profile.upi_id, profile.name, bill.total, 'Bill payment'), 200) : null)
  const onSearchKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (matches[0]) add(matches[0])
      else if (query.trim()) addByCode(query)
    }
  }
  const needsCustomer = mode === 'credit' || (mode === 'split' && splitPaid < bill.total)
  const blocked = !lines.length || (needsCustomer && !hasCustomer) || lines.some((l) => l.quantity > l.stock)

  if (!can('staff')) return <EmptyState title="Viewers can see bills but not create them" />

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <Card>
        <CardHeader
          title="1 · Add items"
          description="Type a name or code and press Enter · F2 jumps here · or scan the barcode"
          action={
            <Button variant="secondary" size="sm" onClick={scanning ? stopScan : startScan}>
              {scanning ? <CameraOff className="size-4" /> : <Camera className="size-4" />} {scanning ? 'Stop' : 'Scan'}
            </Button>
          }
        />
        <div className="space-y-3 px-5 pb-5">
          <video ref={videoRef} className={cn('aspect-video w-full rounded-lg bg-black object-cover', !scanning && 'hidden')} muted playsInline />
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
            <Input ref={searchRef} autoFocus value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={onSearchKey} placeholder="Search product… e.g. basmati, ELC-1001" className="h-11 pl-9" />
            {matches.length > 0 && (
              <div className="absolute inset-x-0 top-12 z-20 overflow-hidden rounded-xl border border-border bg-surface shadow-lg">
                {matches.map((p) => (
                  <button key={p.id} type="button" onClick={() => add(p)} className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-surface-2">
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{p.name}</span>
                      <span className="font-mono text-xs text-subtle">{p.sku} · {number(p.on_hand)} in stock</span>
                    </span>
                    <span className="tabular-nums">{money(inclusive && gstOn ? p.price_incl_gst : p.unit_price)}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          {!lines.length ? (
            <EmptyState icon={<ReceiptIndianRupee className="size-6" />} title="No items yet" description="Search above or scan a barcode to start the bill." />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Item</Th>
                  <Th className="w-32 text-center">Qty</Th>
                  <Th className="w-32 text-right">Price</Th>
                  <Th className="w-20 text-right">Disc %</Th>
                  <Th className="text-right">Amount</Th>
                  <Th className="w-8" />
                </tr>
              </thead>
              <tbody>
                {lines.map((l, i) => (
                  <tr key={l.product_id}>
                    <Td>
                      <div className="font-medium">{l.name}</div>
                      <div className="text-xs text-subtle">
                        {l.sku}
                        {gstOn && ` · GST ${l.gst_rate}%`}
                        {l.quantity > l.stock && <span className="ml-1 font-medium text-critical">· only {l.stock} in stock</span>}
                      </div>
                    </Td>
                    <Td>
                      <div className="flex items-center justify-center gap-1">
                        <Button size="icon" variant="ghost" className="size-7" onClick={() => (l.quantity > 1 ? update(l.product_id, { quantity: l.quantity - 1 }) : setLines((ls) => ls.filter((x) => x.product_id !== l.product_id)))}><Minus className="size-3.5" /></Button>
                        <Input type="number" min={1} value={l.quantity} onChange={(e) => update(l.product_id, { quantity: Math.max(1, Number(e.target.value) || 1) })} className="h-8 w-14 text-center" />
                        <Button size="icon" variant="ghost" className="size-7" onClick={() => update(l.product_id, { quantity: l.quantity + 1 })}><Plus className="size-3.5" /></Button>
                      </div>
                    </Td>
                    <Td><Input type="number" min={0} step="0.01" value={l.unit_price} onChange={(e) => update(l.product_id, { unit_price: Math.max(0, Number(e.target.value) || 0) })} className="h-8 text-right" /></Td>
                    <Td><Input type="number" min={0} max={100} value={l.discount_pct} onChange={(e) => update(l.product_id, { discount_pct: Math.min(100, Math.max(0, Number(e.target.value) || 0)) })} className="h-8 text-right" /></Td>
                    <Td className="text-right font-medium tabular-nums">{money(bill.lines[i]?.total)}</Td>
                    <Td><Button size="icon" variant="ghost" className="size-7" aria-label="Remove" onClick={() => setLines((ls) => ls.filter((x) => x.product_id !== l.product_id))}><Trash2 className="size-3.5" /></Button></Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          {gstOn && (
            <label className="flex items-center gap-2 text-sm text-muted">
              <Switch checked={inclusive} onCheckedChange={toggleInclusive} label="Prices include GST" /> Prices include GST (MRP style) — switch off for B2B bills
            </label>
          )}
        </div>
      </Card>

      <div className="space-y-4">
        <Card>
          <CardHeader title="2 · Customer" description="Optional — needed for udhaar or a GST bill to a business" />
          <div className="space-y-3 px-5 pb-5">
            {!showCustomer ? (
              <Button variant="secondary" className="w-full" onClick={() => setShowCustomer(true)}><Plus className="size-4" /> Add customer</Button>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Phone"><Input value={customer.phone} onChange={(e) => setPhone(e.target.value)} placeholder="98200 12345" inputMode="tel" /></Field>
                  <Field label="Name"><Input value={customer.name} onChange={(e) => setCustomer({ ...customer, name: e.target.value })} /></Field>
                </div>
                {known && (
                  <div className="rounded-lg bg-surface-2 px-3 py-2 text-xs">
                    Returning customer{known.balance ? <> · <span className="font-medium text-critical">{money(known.balance)} udhaar baaki</span></> : ' · no dues'}
                  </div>
                )}
                <details className="text-sm">
                  <summary className="cursor-pointer text-xs text-muted">More (state, GSTIN, address)</summary>
                  <div className="mt-2 grid gap-2">
                    <Field label="State / place of supply" hint={shopState ? `Blank = ${shopState} (same as shop → CGST + SGST)` : undefined}>
                      <Select value={customer.state} onChange={(e) => setCustomer({ ...customer, state: e.target.value })}>
                        <option value="">Same as shop</option>
                        {settings?.states.map((s) => <option key={s}>{s}</option>)}
                        <option>Outside India</option>
                      </Select>
                    </Field>
                    <Field label="GSTIN (business customers)"><Input value={customer.gstin} onChange={(e) => setCustomer({ ...customer, gstin: e.target.value.toUpperCase() })} maxLength={15} className="font-mono" /></Field>
                    <Field label="Address"><Input value={customer.address} onChange={(e) => setCustomer({ ...customer, address: e.target.value })} /></Field>
                  </div>
                </details>
              </>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="3 · Payment" />
          <div className="space-y-3 px-5 pb-5">
            <div className="flex flex-wrap gap-1.5">
              {(['cash', 'upi', 'card', 'split', 'credit'] as Mode[]).map((m) => (
                <button key={m} type="button" onClick={() => setMode(m)} className={cn('rounded-lg border px-3 py-1.5 text-sm font-medium transition', mode === m ? 'border-brand bg-brand-soft text-brand' : 'border-border hover:bg-surface-2')}>
                  {MODE_LABEL[m]}
                </button>
              ))}
            </div>
            {mode === 'cash' && (
              <Field label="Cash received (optional)">
                <Input type="number" value={cashGiven} onChange={(e) => setCashGiven(e.target.value)} placeholder={String(bill.total)} />
                {Number(cashGiven) > bill.total && <div className="mt-1 text-sm font-medium text-good">Return change: {money(Number(cashGiven) - bill.total)}</div>}
              </Field>
            )}
            {mode === 'upi' && (
              <div className="space-y-2">
                {profile?.upi_id ? (
                  <Button variant="secondary" className="w-full" onClick={showQr} disabled={!bill.total}><QrCode className="size-4" /> Show UPI QR for {money(bill.total)}</Button>
                ) : (
                  <p className="text-xs text-muted">Add your UPI ID in Settings → Business & GST to show a QR with the exact amount.</p>
                )}
                {qr && (
                  <div className="grid place-items-center rounded-xl border border-border p-3">
                    <img src={qr} alt="UPI QR" className="size-44" />
                    <div className="mt-1 text-xs text-muted">Customer scans with GPay / PhonePe / Paytm / BHIM</div>
                  </div>
                )}
                <Field label="UPI reference / UTR (optional)"><Input value={utr} onChange={(e) => setUtr(e.target.value)} placeholder="e.g. 4256 1234 5678" /></Field>
              </div>
            )}
            {mode === 'split' && (
              <div className="grid grid-cols-2 gap-2">
                <Field label="Cash"><Input type="number" value={split.cash} onChange={(e) => setSplit({ ...split, cash: e.target.value })} /></Field>
                <Field label="UPI"><Input type="number" value={split.upi} onChange={(e) => setSplit({ ...split, upi: e.target.value })} /></Field>
                {splitPaid < bill.total && lines.length > 0 && <p className="col-span-2 text-xs text-warning">{money(bill.total - splitPaid)} will go on the customer&apos;s khata.</p>}
              </div>
            )}
            {mode === 'credit' && <p className="text-xs text-muted">The full amount goes on the customer&apos;s khata (udhaar). You can send a WhatsApp reminder later.</p>}
            {needsCustomer && !hasCustomer && <p className="text-xs font-medium text-critical">Add the customer&apos;s name and phone for udhaar.</p>}

            <div className="space-y-1 border-t border-border pt-3 text-sm">
              {bill.discount > 0 && <Row label="Discount" value={`−${money(bill.discount)}`} />}
              {gstOn && <Row label="Taxable value" value={money(bill.taxable)} />}
              {gstOn && (exportSale ? <Row label="IGST (export, zero-rated)" value={money(0)} /> : interstate ? <Row label="IGST" value={money(bill.igst)} /> : <><Row label="CGST" value={money(bill.cgst)} /><Row label="SGST" value={money(bill.sgst)} /></>)}
              {bill.roundOff !== 0 && <Row label="Round off" value={bill.roundOff.toFixed(2)} />}
              <div className="flex items-baseline justify-between pt-1">
                <span className="font-medium">Total</span>
                <span className="text-2xl font-semibold tabular-nums">{money(bill.total)}</span>
              </div>
            </div>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={reset} disabled={!lines.length}><X className="size-4" /> Clear</Button>
              <Button size="lg" className="flex-1" disabled={blocked} loading={save.isPending} onClick={() => save.mutate(undefined)}>
                <ReceiptIndianRupee className="size-4" /> Save bill
              </Button>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}

const Row = ({ label, value }: { label: string; value: string }) => (
  <div className="flex justify-between text-muted"><span>{label}</span><span className="tabular-nums">{value}</span></div>
)

// --- Invoice list & detail -----------------------------------------------------------------

function InvoiceList({ onOpen }: { onOpen: (id: number) => void }) {
  const [status, setStatus] = useState<'all' | 'due' | 'paid' | 'cancelled'>('all')
  const [q, setQ] = useState('')
  const invoices = useInvoices(status, q)
  const { can } = useAuth()
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 p-4">
        <Segmented size="sm" value={status} onChange={setStatus} options={[{ value: 'all', label: 'All' }, { value: 'due', label: 'Udhaar / due' }, { value: 'paid', label: 'Paid' }, { value: 'cancelled', label: 'Cancelled' }]} />
        <div className="relative ml-auto">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Bill no., name or phone" className="w-64 pl-9" />
        </div>
        {can('manager') && (
          <Button variant="secondary" size="sm" onClick={() => download('/api/invoices/export.csv?days=31', 'sales-register.csv').catch((e: Error) => toast.error(e.message))}>
            <Download className="size-4" /> Sales register (CSV for CA)
          </Button>
        )}
      </div>
      {invoices.isLoading ? <Skeleton className="m-5 h-48" /> : !invoices.data?.length ? <EmptyState title="No bills found" /> : (
        <Table>
          <thead><tr><Th>Bill no.</Th><Th>Date</Th><Th>Customer</Th><Th>Mode</Th><Th className="text-right">Total</Th><Th className="text-right">Balance</Th><Th>Status</Th></tr></thead>
          <tbody>
            {invoices.data.map((i) => (
              <tr key={i.id} className="cursor-pointer hover:bg-surface-2" onClick={() => onOpen(i.id)}>
                <Td className="font-mono text-xs">{i.number}</Td>
                <Td className="text-muted">{dateTime(i.created_at)}</Td>
                <Td>{i.customer_name}<div className="text-xs text-subtle">{i.customer_phone}</div></Td>
                <Td>{MODE_LABEL[i.payment_mode]}</Td>
                <Td className="text-right font-medium tabular-nums">{money(i.total)}</Td>
                <Td className={cn('text-right tabular-nums', i.balance > 0 && 'font-medium text-critical')}>{i.balance ? money(i.balance) : '—'}</Td>
                <Td><Badge tone={STATUS[i.status].tone}>{STATUS[i.status].label}</Badge></Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

function InvoiceDialog({ id, onClose }: { id: number; onClose: () => void }) {
  const inv = useInvoice(id).data
  const { can } = useAuth()
  const [paying, setPaying] = useState(false)
  const [pay, setPay] = useState({ amount: '', mode: 'upi', reference: '' })
  const [qrFor, setQrFor] = useState<{ link: string; url: string } | null>(null)
  const link = inv?.upi_link
  useEffect(() => {
    let alive = true
    if (link) void qrDataUrl(link, 160).then((url) => alive && setQrFor({ link, url }))
    return () => {
      alive = false
    }
  }, [link])
  const qr = link && qrFor?.link === link ? qrFor.url : null
  const receive = useAction(() => post<InvoiceDetail>(`/api/invoices/${id}/payments`, { amount: Number(pay.amount || inv?.balance), mode: pay.mode, reference: pay.reference || null }), {
    success: (r) => (r.balance ? `Received · ${money(r.balance)} still due` : 'Fully paid ✅'),
    invalidate: INVALIDATE,
    onSuccess: () => setPaying(false),
  })
  const cancel = useAction((reason: string) => post<InvoiceDetail>(`/api/invoices/${id}/cancel`, { reason }), { success: 'Bill cancelled — stock returned', invalidate: INVALIDATE })

  return (
    <Dialog
      open
      wide
      onOpenChange={(o) => !o && onClose()}
      title={inv ? <span className="flex items-center gap-2">{inv.title} {inv.number} <Badge tone={STATUS[inv.status].tone}>{STATUS[inv.status].label}</Badge></span> : 'Loading…'}
      description={inv ? `${dateTime(inv.created_at)} · ${inv.customer_name}${inv.customer_phone ? ` · ${inv.customer_phone}` : ''}` : undefined}
      footer={
        inv && (
          <div className="flex w-full flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => printInvoice(inv, 'a4')}><Printer className="size-4" /> Print A4</Button>
            <Button variant="ghost" onClick={() => printInvoice(inv, 'thermal')}><Printer className="size-4" /> Thermal 80mm</Button>
            <a href={whatsappLink(invoiceWhatsApp(inv), inv.customer_phone)} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-2 rounded-lg border border-border px-3.5 text-sm font-medium hover:bg-surface-2">
              <MessageCircle className="size-4" /> WhatsApp
            </a>
            {can('manager') && inv.status !== 'cancelled' && (
              <Button variant="secondary" loading={cancel.isPending} onClick={() => { const r = window.prompt('Why cancel this bill? Stock will be returned.'); if (r !== null) cancel.mutate(r) }}>Cancel bill</Button>
            )}
            {can('staff') && inv.balance > 0 && <Button onClick={() => setPaying(true)}><Wallet className="size-4" /> Receive payment</Button>}
          </div>
        )
      }
    >
      {!inv ? <Skeleton className="h-64" /> : (
        <div className="space-y-4">
          <Table>
            <thead><tr><Th>Item</Th><Th className="text-right">Qty</Th><Th className="text-right">Rate</Th>{inv.kind !== 'bill_of_supply' && <Th className="text-right">GST</Th>}<Th className="text-right">Amount</Th></tr></thead>
            <tbody>
              {inv.lines.map((l) => (
                <tr key={l.id}>
                  <Td>{l.name}<div className="text-xs text-subtle">{l.sku}{l.hsn_code ? ` · HSN ${l.hsn_code}` : ''}{l.discount_pct ? ` · ${l.discount_pct}% off` : ''}</div></Td>
                  <Td className="text-right tabular-nums">{l.quantity}</Td>
                  <Td className="text-right tabular-nums">{money(l.unit_price)}</Td>
                  {inv.kind !== 'bill_of_supply' && <Td className="text-right tabular-nums">{l.gst_rate}%</Td>}
                  <Td className="text-right font-medium tabular-nums">{money(l.total)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2 text-sm">
              {inv.payments.length > 0 && (
                <div>
                  <div className="mb-1 text-xs font-medium text-muted">Payments</div>
                  {inv.payments.map((p, i) => <div key={i} className="flex justify-between"><span>{MODE_LABEL[p.mode] ?? p.mode}{p.reference ? ` · ${p.reference}` : ''} <span className="text-subtle">{shortDate(p.created_at)}</span></span><span className="tabular-nums">{money(p.amount)}</span></div>)}
                </div>
              )}
              {inv.notes.map((n) => <p key={n} className="text-xs text-muted">{n}</p>)}
              <p className="text-xs text-subtle italic">{inv.amount_in_words}</p>
              {qr && <div className="flex items-center gap-3"><img src={qr} alt="UPI QR" className="size-28 rounded-lg border border-border" /><span className="text-xs text-muted">Scan to pay the balance {money(inv.balance)} by UPI</span></div>}
            </div>
            <div className="space-y-1 text-sm">
              {inv.discount > 0 && <Row label="Discount" value={`−${money(inv.discount)}`} />}
              <Row label="Taxable value" value={money(inv.taxable)} />
              {inv.kind !== 'bill_of_supply' && (inv.interstate ? <Row label="IGST" value={money(inv.igst)} /> : <><Row label="CGST" value={money(inv.cgst)} /><Row label="SGST" value={money(inv.sgst)} /></>)}
              {inv.round_off !== 0 && <Row label="Round off" value={inv.round_off.toFixed(2)} />}
              <div className="flex justify-between pt-1 text-base font-semibold"><span>Total</span><span className="tabular-nums">{money(inv.total)}</span></div>
              {inv.balance > 0 && <div className="flex justify-between font-medium text-critical"><span>Balance due</span><span className="tabular-nums">{money(inv.balance)}</span></div>}
            </div>
          </div>
          {paying && (
            <Card className="grid gap-2 p-4 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end">
              <Field label="Amount"><Input type="number" value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} placeholder={String(inv.balance)} /></Field>
              <Field label="Mode"><Select value={pay.mode} onChange={(e) => setPay({ ...pay, mode: e.target.value })}>{['upi', 'cash', 'card', 'bank'].map((m) => <option key={m} value={m}>{MODE_LABEL[m]}</option>)}</Select></Field>
              <Field label="UTR / ref (optional)"><Input value={pay.reference} onChange={(e) => setPay({ ...pay, reference: e.target.value })} /></Field>
              <Button onClick={() => receive.mutate(undefined)} loading={receive.isPending}>Save</Button>
            </Card>
          )}
        </div>
      )}
    </Dialog>
  )
}

// --- Khata ----------------------------------------------------------------------------------

function Khata({ onOpen }: { onOpen: (id: number) => void }) {
  const dues = useDues()
  const profile = useBillingProfile().data
  const [collecting, setCollecting] = useState<CustomerDue | null>(null)
  const total = dues.data?.reduce((s, d) => s + d.balance, 0) ?? 0
  return (
    <Card>
      <CardHeader title="Khata — who owes you money" description={dues.data?.length ? `${dues.data.length} customer(s) · ${money(total)} to collect` : undefined} icon={<BookUser className="size-4" />} />
      {dues.isLoading ? <Skeleton className="m-5 h-40" /> : !dues.data?.length ? <EmptyState title="No udhaar 🎉" description="Everyone has paid in full." /> : (
        <Table>
          <thead><tr><Th>Customer</Th><Th>Bills</Th><Th className="text-right">Since</Th><Th className="text-right">Balance</Th><Th className="text-right">Actions</Th></tr></thead>
          <tbody>
            {dues.data.map((d) => (
              <tr key={d.customer_id}>
                <Td className="font-medium">{d.name}<div className="text-xs font-normal text-subtle">{d.phone}</div></Td>
                <Td><div className="flex flex-wrap gap-1">{d.invoices.map((i) => <button key={i.id} onClick={() => onOpen(i.id)} className="font-mono text-xs text-brand hover:underline">{i.number}</button>)}</div></Td>
                <Td className={cn('text-right tabular-nums', d.days_outstanding > 30 ? 'font-medium text-critical' : 'text-muted')}>{d.days_outstanding} days</Td>
                <Td className="text-right font-semibold tabular-nums">{money(d.balance)}</Td>
                <Td>
                  <div className="flex justify-end gap-1.5">
                    {profile && (
                      <a href={whatsappLink(duesReminder(d, profile), d.phone)} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-2.5 text-xs font-medium hover:bg-surface-2">
                        <MessageCircle className="size-3.5" /> Remind
                      </a>
                    )}
                    <Button size="sm" onClick={() => setCollecting(d)}><Wallet className="size-3.5" /> Collect</Button>
                  </div>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {collecting && <CollectDialog due={collecting} onClose={() => setCollecting(null)} />}
    </Card>
  )
}

/** Receive money from a customer; it settles their oldest bills first. */
function CollectDialog({ due, onClose }: { due: CustomerDue; onClose: () => void }) {
  const [amount, setAmount] = useState(String(due.balance))
  const [mode, setMode] = useState('upi')
  const [reference, setReference] = useState('')
  const collect = useAction(
    async () => {
      let left = Number(amount) || 0
      for (const inv of due.invoices) {
        if (left <= 0) break
        const part = Math.min(left, inv.balance)
        await post(`/api/invoices/${inv.id}/payments`, { amount: part, mode, reference: reference || null })
        left = Math.round((left - part) * 100) / 100
      }
    },
    { success: `Payment from ${due.name} saved`, invalidate: INVALIDATE, onSuccess: onClose },
  )
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={`Collect from ${due.name}`} description={`${money(due.balance)} due · oldest bill is settled first`} footer={<Button onClick={() => collect.mutate(undefined)} loading={collect.isPending} disabled={!(Number(amount) > 0)}>Save payment</Button>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Amount received"><Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        <Field label="Mode"><Select value={mode} onChange={(e) => setMode(e.target.value)}>{['upi', 'cash', 'card', 'bank'].map((m) => <option key={m} value={m}>{MODE_LABEL[m]}</option>)}</Select></Field>
        <Field label="UTR / reference (optional)" className="sm:col-span-2"><Input value={reference} onChange={(e) => setReference(e.target.value)} /></Field>
      </div>
    </Dialog>
  )
}
