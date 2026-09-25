/** Billing: make a bill in 3 steps (items → customer → payment), invoices list and the udhaar khata. */
import { BookUser, Calculator, Camera, CameraOff, Download, IndianRupee, MessageCircle, Minus, Plus, Printer, QrCode, ReceiptIndianRupee, Search, Trash2, Wallet, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, Field, Input, PageHeader, Segmented, Select, Skeleton, Switch, Table, Tabs, TabsContent, TabsList, TabsTrigger, Td, Th, type Tone } from '@/components/ui'
import { useAction, useBillingProfile, useBillingSummary, useCustomers, useDayClose, useDues, useGstSettings, useInvoice, useInvoices, useProducts } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { useBarcodeScanner } from '@/hooks/useBarcodeScanner'
import { download, post } from '@/lib/api'
import { duesReminder, invoiceWhatsApp, previewBill, printInvoice, qrDataUrl, upiLink, type DraftLine } from '@/lib/billing'
import { whatsappLink } from '@/lib/speech'
import type { CustomerDue, DayClose, InvoiceDetail, InvoiceStatus, PaymentMode, ProductRow } from '@/lib/types'
import { cn, dateTime, longDate, money, number, shortDate } from '@/lib/utils'
import { tr, useT } from '@/lib/i18n'

const INVALIDATE = [['invoices'], ['invoice'], ['billing'], ['customers'], ['products'], ['dashboard'], ['gst']]

const MODE_LABEL: Record<string, string> = { cash: 'Cash', upi: 'UPI', card: 'Card', bank: 'Bank', credit: 'Udhaar', split: 'Split' }
const STATUS: Record<InvoiceStatus, { tone: Tone; label: string }> = {
  paid: { tone: 'good', label: 'Paid' },
  partial: { tone: 'warning', label: 'Part paid' },
  unpaid: { tone: 'critical', label: 'Udhaar' },
  cancelled: { tone: 'neutral', label: 'Cancelled' },
}

export default function Billing() {
  const t = useT()
  const [params, setParams] = useSearchParams()
  const [openId, setOpenId] = useState<number | null>(null)
  return (
    <div>
      <PageHeader title={t('Billing')} description={t('Make a bill in 3 steps, share it on WhatsApp, collect by UPI and keep track of udhaar.')} />
      <SummaryStrip />
      <Tabs value={params.get('tab') ?? 'new'} onValueChange={(tab) => setParams({ tab }, { replace: true })}>
        <TabsList>
          <TabsTrigger value="new"><ReceiptIndianRupee className="size-4" /> {t('New bill')}</TabsTrigger>
          <TabsTrigger value="invoices"><IndianRupee className="size-4" /> {t('All bills')}</TabsTrigger>
          <TabsTrigger value="khata"><BookUser className="size-4" /> {t('Khata (udhaar)')}</TabsTrigger>
          <TabsTrigger value="hisaab"><Calculator className="size-4" /> {t('Aaj ka hisaab')}</TabsTrigger>
        </TabsList>
        <TabsContent value="new"><NewBill onSaved={setOpenId} /></TabsContent>
        <TabsContent value="invoices"><InvoiceList onOpen={setOpenId} /></TabsContent>
        <TabsContent value="khata"><Khata onOpen={setOpenId} /></TabsContent>
        <TabsContent value="hisaab"><DayCloseCard /></TabsContent>
      </Tabs>
      {openId && <InvoiceDialog id={openId} onClose={() => setOpenId(null)} />}
    </div>
  )
}

function SummaryStrip() {
  const t = useT()
  const s = useBillingSummary(7).data
  const items = [
    { label: t("Today's sales"), value: money(s?.today.sales), hint: `${s?.today.bills ?? 0} ${t('bills')}` },
    { label: t('Last 7 days'), value: money(s?.period.sales), hint: `${s?.period.bills ?? 0} ${t('bills')} · ${t('avg')} ${money(s?.period.avg_bill)}` },
    { label: t('Udhaar to collect'), value: money(s?.outstanding), hint: `${s?.customers_with_dues ?? 0} ${t('customer(s)')}`, tone: s?.outstanding ? 'text-critical' : '' },
    { label: t('Collected by UPI (7d)'), value: money(s?.collected_by_mode.upi ?? 0), hint: `${t('Cash')} ${money(s?.collected_by_mode.cash ?? 0)}` },
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
  const t = useT()
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
    return (products.data ?? []).filter((p) => p.is_active && (p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q) || (p.barcode ?? '').startsWith(q))).slice(0, 8)
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
  // barcode (USB scanner types it + Enter, or the camera) or SKU
  const addByCode = (code: string) => {
    const c = code.trim().replace(/^ii:/i, '').toLowerCase()
    const p = products.data?.find((x) => x.barcode === c || x.sku.toLowerCase() === c)
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
      const exact = products.data?.find((x) => x.barcode === query.trim())
      if (exact) add(exact)
      else if (matches[0]) add(matches[0])
      else if (query.trim()) addByCode(query)
    }
  }
  const needsCustomer = mode === 'credit' || (mode === 'split' && splitPaid < bill.total)
  const blocked = !lines.length || (needsCustomer && !hasCustomer) || lines.some((l) => l.quantity > l.stock)

  if (!can('staff')) return <EmptyState title={t('Viewers can see bills but not create them')} />

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <Card>
        <CardHeader
          title={t('1 · Add items')}
          description={t('Type a name or code and press Enter · F2 jumps here · or scan the barcode')}
          action={
            <Button variant="secondary" size="sm" onClick={scanning ? stopScan : startScan}>
              {scanning ? <CameraOff className="size-4" /> : <Camera className="size-4" />} {scanning ? t('Stop') : t('Scan')}
            </Button>
          }
        />
        <div className="space-y-3 px-5 pb-5">
          <video ref={videoRef} className={cn('aspect-video w-full rounded-lg bg-black object-cover', !scanning && 'hidden')} muted playsInline />
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
            <Input ref={searchRef} autoFocus value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={onSearchKey} placeholder={t('Search product… e.g. atta, sugar, ATA-101')} className="h-11 pl-9" />
            {matches.length > 0 && (
              <div className="absolute inset-x-0 top-12 z-20 overflow-hidden rounded-xl border border-border bg-surface shadow-lg">
                {matches.map((p) => (
                  <button key={p.id} type="button" onClick={() => add(p)} className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-surface-2">
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{p.name}</span>
                      <span className="font-mono text-xs text-subtle">{p.sku} · {number(p.on_hand)} {t('in stock')}</span>
                    </span>
                    <span className="tabular-nums">{money(inclusive && gstOn ? p.price_incl_gst : p.unit_price)}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          {!lines.length ? (
            <EmptyState icon={<ReceiptIndianRupee className="size-6" />} title={t('No items yet')} description={t('Search above or scan a barcode to start the bill.')} />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>{t('Item')}</Th>
                  <Th className="w-32 text-center">{t('Qty')}</Th>
                  <Th className="w-32 text-right">{t('Price')}</Th>
                  <Th className="w-20 text-right">{t('Disc %')}</Th>
                  <Th className="text-right">{t('Amount')}</Th>
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
                        {l.quantity > l.stock && <span className="ml-1 font-medium text-critical">· {t('only {n} in stock', { n: l.stock })}</span>}
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
                    <Td><Button size="icon" variant="ghost" className="size-7" aria-label={t('Remove')} onClick={() => setLines((ls) => ls.filter((x) => x.product_id !== l.product_id))}><Trash2 className="size-3.5" /></Button></Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          {gstOn && (
            <label className="flex items-center gap-2 text-sm text-muted">
              <Switch checked={inclusive} onCheckedChange={toggleInclusive} label={t('Prices include GST')} /> {t('Prices include GST (MRP style) — switch off for B2B bills')}
            </label>
          )}
        </div>
      </Card>

      <div className="space-y-4">
        <Card>
          <CardHeader title={t('2 · Customer')} description={t('Optional — needed for udhaar or a GST bill to a business')} />
          <div className="space-y-3 px-5 pb-5">
            {!showCustomer ? (
              <Button variant="secondary" className="w-full" onClick={() => setShowCustomer(true)}><Plus className="size-4" /> {t('Add customer')}</Button>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <Field label={t('Phone')}><Input value={customer.phone} onChange={(e) => setPhone(e.target.value)} placeholder="98200 12345" inputMode="tel" /></Field>
                  <Field label={t('Name')}><Input value={customer.name} onChange={(e) => setCustomer({ ...customer, name: e.target.value })} /></Field>
                </div>
                {known && (
                  <div className="rounded-lg bg-surface-2 px-3 py-2 text-xs">
                    {t('Returning customer')}{known.balance ? <> · <span className="font-medium text-critical">{money(known.balance)} {t('udhaar baaki')}</span></> : ` · ${t('no dues')}`}
                  </div>
                )}
                <details className="text-sm">
                  <summary className="cursor-pointer text-xs text-muted">{t('More (state, GSTIN, address)')}</summary>
                  <div className="mt-2 grid gap-2">
                    <Field label={t('State / place of supply')} hint={shopState ? `Blank = ${shopState} (same as shop → CGST + SGST)` : undefined}>
                      <Select value={customer.state} onChange={(e) => setCustomer({ ...customer, state: e.target.value })}>
                        <option value="">{t('Same as shop')}</option>
                        {settings?.states.map((s) => <option key={s}>{s}</option>)}
                        <option>Outside India</option>
                      </Select>
                    </Field>
                    <Field label={t('GSTIN (business customers)')}><Input value={customer.gstin} onChange={(e) => setCustomer({ ...customer, gstin: e.target.value.toUpperCase() })} maxLength={15} className="font-mono" /></Field>
                    <Field label={t('Address')}><Input value={customer.address} onChange={(e) => setCustomer({ ...customer, address: e.target.value })} /></Field>
                  </div>
                </details>
              </>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title={t('3 · Payment')} />
          <div className="space-y-3 px-5 pb-5">
            <div className="flex flex-wrap gap-1.5">
              {(['cash', 'upi', 'card', 'split', 'credit'] as Mode[]).map((m) => (
                <button key={m} type="button" onClick={() => setMode(m)} className={cn('rounded-lg border px-3 py-1.5 text-sm font-medium transition', mode === m ? 'border-brand bg-brand-soft text-brand' : 'border-border hover:bg-surface-2')}>
                  {t(MODE_LABEL[m])}
                </button>
              ))}
            </div>
            {mode === 'cash' && (
              <Field label={t('Cash received (optional)')}>
                <Input type="number" value={cashGiven} onChange={(e) => setCashGiven(e.target.value)} placeholder={String(bill.total)} />
                {Number(cashGiven) > bill.total && <div className="mt-1 text-sm font-medium text-good">{t('Return change:')} {money(Number(cashGiven) - bill.total)}</div>}
              </Field>
            )}
            {mode === 'upi' && (
              <div className="space-y-2">
                {profile?.upi_id ? (
                  <Button variant="secondary" className="w-full" onClick={showQr} disabled={!bill.total}><QrCode className="size-4" /> {t('Show UPI QR for')} {money(bill.total)}</Button>
                ) : (
                  <p className="text-xs text-muted">{t('Add your UPI ID in Settings → Business & GST to show a QR with the exact amount.')}</p>
                )}
                {qr && (
                  <div className="grid place-items-center rounded-xl border border-border p-3">
                    <img src={qr} alt={t('UPI QR')} className="size-44" />
                    <div className="mt-1 text-xs text-muted">{t('Customer scans with GPay / PhonePe / Paytm / BHIM')}</div>
                  </div>
                )}
                <Field label={t('UPI reference / UTR (optional)')}><Input value={utr} onChange={(e) => setUtr(e.target.value)} placeholder={t('e.g. 4256 1234 5678')} /></Field>
              </div>
            )}
            {mode === 'split' && (
              <div className="grid grid-cols-2 gap-2">
                <Field label={t('Cash')}><Input type="number" value={split.cash} onChange={(e) => setSplit({ ...split, cash: e.target.value })} /></Field>
                <Field label={t('UPI')}><Input type="number" value={split.upi} onChange={(e) => setSplit({ ...split, upi: e.target.value })} /></Field>
                {splitPaid < bill.total && lines.length > 0 && <p className="col-span-2 text-xs text-warning">{money(bill.total - splitPaid)} {t("will go on the customer's khata.")}</p>}
              </div>
            )}
            {mode === 'credit' && <p className="text-xs text-muted">{t("The full amount goes on the customer's khata (udhaar). You can send a WhatsApp reminder later.")}</p>}
            {needsCustomer && !hasCustomer && <p className="text-xs font-medium text-critical">{t("Add the customer's name and phone for udhaar.")}</p>}

            <div className="space-y-1 border-t border-border pt-3 text-sm">
              {bill.discount > 0 && <Row label={t('Discount')} value={`−${money(bill.discount)}`} />}
              {gstOn && <Row label={t('Taxable value')} value={money(bill.taxable)} />}
              {gstOn && (exportSale ? <Row label={t('IGST (export, zero-rated)')} value={money(0)} /> : interstate ? <Row label={t('IGST')} value={money(bill.igst)} /> : <><Row label={t('CGST')} value={money(bill.cgst)} /><Row label={t('SGST')} value={money(bill.sgst)} /></>)}
              {bill.roundOff !== 0 && <Row label={t('Round off')} value={bill.roundOff.toFixed(2)} />}
              <div className="flex items-baseline justify-between pt-1">
                <span className="font-medium">{t('Total')}</span>
                <span className="text-2xl font-semibold tabular-nums">{money(bill.total)}</span>
              </div>
            </div>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={reset} disabled={!lines.length}><X className="size-4" /> {t('Clear')}</Button>
              <Button size="lg" className="flex-1" disabled={blocked} loading={save.isPending} onClick={() => save.mutate(undefined)}>
                <ReceiptIndianRupee className="size-4" /> {t('Save bill')}
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
  const t = useT()
  const [status, setStatus] = useState<'all' | 'due' | 'paid' | 'cancelled'>('all')
  const [q, setQ] = useState('')
  const invoices = useInvoices(status, q)
  const { can } = useAuth()
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 p-4">
        <Segmented size="sm" value={status} onChange={setStatus} options={[{ value: 'all', label: t('All') }, { value: 'due', label: t('Udhaar / due') }, { value: 'paid', label: t('Paid') }, { value: 'cancelled', label: t('Cancelled') }]} />
        <div className="relative ml-auto">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('Bill no., name or phone')} className="w-64 pl-9" />
        </div>
        {can('manager') && (
          <Button variant="secondary" size="sm" onClick={() => download('/api/invoices/export.csv?days=31', 'sales-register.csv').catch((e: Error) => toast.error(e.message))}>
            <Download className="size-4" /> {t('Sales register (CSV for CA)')}
          </Button>
        )}
      </div>
      {invoices.isLoading ? <Skeleton className="m-5 h-48" /> : !invoices.data?.length ? <EmptyState title={t('No bills found')} /> : (
        <Table>
          <thead><tr><Th>{t('Bill no.')}</Th><Th>{t('Date')}</Th><Th>{t('Customer')}</Th><Th>{t('Mode')}</Th><Th className="text-right">{t('Total')}</Th><Th className="text-right">{t('Balance')}</Th><Th>{t('Status')}</Th></tr></thead>
          <tbody>
            {invoices.data.map((i) => (
              <tr key={i.id} className="cursor-pointer hover:bg-surface-2" onClick={() => onOpen(i.id)}>
                <Td className="font-mono text-xs">{i.number}</Td>
                <Td className="text-muted">{dateTime(i.created_at)}</Td>
                <Td>{i.customer_name}<div className="text-xs text-subtle">{i.customer_phone}</div></Td>
                <Td>{t(MODE_LABEL[i.payment_mode])}</Td>
                <Td className="text-right font-medium tabular-nums">{money(i.total)}</Td>
                <Td className={cn('text-right tabular-nums', i.balance > 0 && 'font-medium text-critical')}>{i.balance ? money(i.balance) : '—'}</Td>
                <Td><Badge tone={STATUS[i.status].tone}>{t(STATUS[i.status].label)}</Badge></Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

function InvoiceDialog({ id, onClose }: { id: number; onClose: () => void }) {
  const t = useT()
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
  const cancel = useAction((reason: string) => post<InvoiceDetail>(`/api/invoices/${id}/cancel`, { reason }), { success: t('Bill cancelled — stock returned'), invalidate: INVALIDATE })

  return (
    <Dialog
      open
      wide
      onOpenChange={(o) => !o && onClose()}
      title={inv ? <span className="flex items-center gap-2">{inv.title} {inv.number} <Badge tone={STATUS[inv.status].tone}>{t(STATUS[inv.status].label)}</Badge></span> : 'Loading…'}
      description={inv ? `${dateTime(inv.created_at)} · ${inv.customer_name}${inv.customer_phone ? ` · ${inv.customer_phone}` : ''}` : undefined}
      footer={
        inv && (
          <div className="flex w-full flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => printInvoice(inv, 'a4')}><Printer className="size-4" /> {t('Print A4')}</Button>
            <Button variant="ghost" onClick={() => printInvoice(inv, 'thermal')}><Printer className="size-4" /> {t('Thermal 80mm')}</Button>
            <a href={whatsappLink(invoiceWhatsApp(inv), inv.customer_phone)} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-2 rounded-lg border border-border px-3.5 text-sm font-medium hover:bg-surface-2">
              <MessageCircle className="size-4" /> {t('WhatsApp')}
            </a>
            {can('manager') && inv.status !== 'cancelled' && (
              <Button variant="secondary" loading={cancel.isPending} onClick={() => { const r = window.prompt(t('Why cancel this bill? Stock will be returned.')); if (r !== null) cancel.mutate(r) }}>{t('Cancel bill')}</Button>
            )}
            {can('staff') && inv.balance > 0 && <Button onClick={() => setPaying(true)}><Wallet className="size-4" /> {t('Receive payment')}</Button>}
          </div>
        )
      }
    >
      {!inv ? <Skeleton className="h-64" /> : (
        <div className="space-y-4">
          <Table>
            <thead><tr><Th>{t('Item')}</Th><Th className="text-right">{t('Qty')}</Th><Th className="text-right">{t('Rate')}</Th>{inv.kind !== 'bill_of_supply' && <Th className="text-right">{t('GST')}</Th>}<Th className="text-right">{t('Amount')}</Th></tr></thead>
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
                  <div className="mb-1 text-xs font-medium text-muted">{t('Payments')}</div>
                  {inv.payments.map((p, i) => <div key={i} className="flex justify-between"><span>{t(MODE_LABEL[p.mode] ?? p.mode)}{p.reference ? ` · ${p.reference}` : ''} <span className="text-subtle">{shortDate(p.created_at)}</span></span><span className="tabular-nums">{money(p.amount)}</span></div>)}
                </div>
              )}
              {inv.notes.map((n) => <p key={n} className="text-xs text-muted">{n}</p>)}
              <p className="text-xs text-subtle italic">{inv.amount_in_words}</p>
              {qr && <div className="flex items-center gap-3"><img src={qr} alt={t('UPI QR')} className="size-28 rounded-lg border border-border" /><span className="text-xs text-muted">Scan to pay the balance {money(inv.balance)} by UPI</span></div>}
            </div>
            <div className="space-y-1 text-sm">
              {inv.discount > 0 && <Row label={t('Discount')} value={`−${money(inv.discount)}`} />}
              <Row label={t('Taxable value')} value={money(inv.taxable)} />
              {inv.kind !== 'bill_of_supply' && (inv.interstate ? <Row label={t('IGST')} value={money(inv.igst)} /> : <><Row label={t('CGST')} value={money(inv.cgst)} /><Row label={t('SGST')} value={money(inv.sgst)} /></>)}
              {inv.round_off !== 0 && <Row label={t('Round off')} value={inv.round_off.toFixed(2)} />}
              <div className="flex justify-between pt-1 text-base font-semibold"><span>{t('Total')}</span><span className="tabular-nums">{money(inv.total)}</span></div>
              {inv.balance > 0 && <div className="flex justify-between font-medium text-critical"><span>{t('Balance due')}</span><span className="tabular-nums">{money(inv.balance)}</span></div>}
            </div>
          </div>
          {paying && (
            <Card className="grid gap-2 p-4 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end">
              <Field label={t('Amount')}><Input type="number" value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} placeholder={String(inv.balance)} /></Field>
              <Field label={t('Mode')}><Select value={pay.mode} onChange={(e) => setPay({ ...pay, mode: e.target.value })}>{['upi', 'cash', 'card', 'bank'].map((m) => <option key={m} value={m}>{t(MODE_LABEL[m])}</option>)}</Select></Field>
              <Field label={t('UTR / ref (optional)')}><Input value={pay.reference} onChange={(e) => setPay({ ...pay, reference: e.target.value })} /></Field>
              <Button onClick={() => receive.mutate(undefined)} loading={receive.isPending}>{t('Save')}</Button>
            </Card>
          )}
        </div>
      )}
    </Dialog>
  )
}

// --- Khata ----------------------------------------------------------------------------------

function Khata({ onOpen }: { onOpen: (id: number) => void }) {
  const t = useT()
  const dues = useDues()
  const profile = useBillingProfile().data
  const [collecting, setCollecting] = useState<CustomerDue | null>(null)
  const total = dues.data?.reduce((s, d) => s + d.balance, 0) ?? 0
  return (
    <Card>
      <CardHeader title={t('Khata — who owes you money')} description={dues.data?.length ? `${dues.data.length} customer(s) · ${money(total)} to collect` : undefined} icon={<BookUser className="size-4" />} />
      {dues.isLoading ? <Skeleton className="m-5 h-40" /> : !dues.data?.length ? <EmptyState title={t('No udhaar 🎉')} description={t('Everyone has paid in full.')} /> : (
        <Table>
          <thead><tr><Th>{t('Customer')}</Th><Th>{t('Bills')}</Th><Th className="text-right">{t('Since')}</Th><Th className="text-right">{t('Balance')}</Th><Th className="text-right">{t('Actions')}</Th></tr></thead>
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
                        <MessageCircle className="size-3.5" /> {t('Remind')}
                      </a>
                    )}
                    <Button size="sm" onClick={() => setCollecting(d)}><Wallet className="size-3.5" /> {t('Collect')}</Button>
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
  const t = useT()
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
    <Dialog open onOpenChange={(o) => !o && onClose()} title={`Collect from ${due.name}`} description={`${money(due.balance)} due · oldest bill is settled first`} footer={<Button onClick={() => collect.mutate(undefined)} loading={collect.isPending} disabled={!(Number(amount) > 0)}>{t('Save payment')}</Button>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t('Amount received')}><Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        <Field label={t('Mode')}><Select value={mode} onChange={(e) => setMode(e.target.value)}>{['upi', 'cash', 'card', 'bank'].map((m) => <option key={m} value={m}>{t(MODE_LABEL[m])}</option>)}</Select></Field>
        <Field label={t('UTR / reference (optional)')} className="sm:col-span-2"><Input value={reference} onChange={(e) => setReference(e.target.value)} /></Field>
      </div>
    </Dialog>
  )
}

// --- Aaj ka hisaab (day-end closing) ---------------------------------------------------------------

const todayIST = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })

function hisaabText(d: DayClose, shop: string): string {
  const modes = Object.entries(d.received).map(([m, v]) => `${tr(MODE_LABEL[m] ?? m)}: ${money(v)}`).join('\n')
  const top = d.top_items.slice(0, 5).map((i) => `• ${i.name} × ${i.quantity} = ${money(i.amount)}`).join('\n')
  return `*${shop} — ${tr('Aaj ka hisaab')}*\n${longDate(d.date)}\n\n${tr('Bills today')}: ${d.bills}\n${tr('Sale')}: *${money(d.sales)}*\n${modes}\n${tr('Cash in galla')}: *${money(d.cash_in_drawer)}*\n${tr('Udhaar given')}: ${money(d.udhaar_given)}\n${tr('Udhaar collected')}: ${money(d.udhaar_collected)}\n\n${tr('Top items today')}:\n${top}`
}

function DayCloseCard() {
  const t = useT()
  const [day, setDay] = useState(todayIST)
  const data = useDayClose(day).data
  const shop = useBillingProfile().data?.name ?? ''
  const printIt = () => {
    if (!data) return
    const w = window.open('', '_blank', 'width=420,height=700')
    if (!w) return
    const esc = (x: string) => x.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]!)
    w.document.write(`<!doctype html><html><head><title>${esc(tr('Aaj ka hisaab'))}</title><style>@page{size:80mm auto;margin:3mm}body{width:74mm;font:12px/1.5 ui-monospace,monospace;white-space:pre-wrap}</style></head><body>${esc(hisaabText(data, shop).replace(/\*/g, ''))}<script>window.onload=()=>window.print()</script></body></html>`)
    w.document.close()
  }
  const cards = data
    ? [
        [t('Bills today'), String(data.bills)],
        [t('Sale'), money(data.sales)],
        [t('Cash in galla'), money(data.cash_in_drawer)],
        [t('Udhaar given'), money(data.udhaar_given)],
        [t('Udhaar collected'), money(data.udhaar_collected)],
      ]
    : []
  return (
    <Card>
      <CardHeader
        title={t('Day-end closing')}
        description={data ? longDate(data.date) : undefined}
        icon={<Calculator className="size-4" />}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Input type="date" value={day} max={todayIST()} onChange={(e) => e.target.value && setDay(e.target.value)} className="h-8 w-40" />
            <Button size="sm" variant="secondary" onClick={printIt} disabled={!data}><Printer className="size-4" /> {t('Print hisaab')}</Button>
            {data && (
              <a href={whatsappLink(hisaabText(data, shop))} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-2.5 text-xs font-medium hover:bg-surface-2">
                <MessageCircle className="size-3.5" /> {t('Share on WhatsApp')}
              </a>
            )}
          </div>
        }
      />
      {!data ? <Skeleton className="m-5 h-40" /> : (
        <div className="space-y-4 px-5 pb-5">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {cards.map(([label, value]) => (
              <div key={label} className="rounded-lg border border-border p-3">
                <div className="text-xs text-muted">{label}</div>
                <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
              </div>
            ))}
          </div>
          {!data.bills ? <EmptyState title={t('No bills on this day')} /> : (
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <div className="mb-2 text-sm font-medium">{t('Received by mode')}</div>
                {Object.entries(data.received).map(([m, v]) => (
                  <div key={m} className="flex justify-between border-b border-border py-1.5 text-sm"><span>{t(MODE_LABEL[m] ?? m)}</span><span className="tabular-nums">{money(v)}</span></div>
                ))}
              </div>
              <div>
                <div className="mb-2 text-sm font-medium">{t('Top items today')}</div>
                {data.top_items.map((i) => (
                  <div key={i.sku} className="flex justify-between border-b border-border py-1.5 text-sm"><span className="truncate">{i.name} × {i.quantity}</span><span className="tabular-nums">{money(i.amount)}</span></div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}
