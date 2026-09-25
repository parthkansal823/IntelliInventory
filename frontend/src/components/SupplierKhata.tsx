/** Supplier khata (payables): what the shop owes each wholesaler, due dates, pay by cash / UPI QR / bank. */
import { AlertTriangle, CalendarClock, Factory, IndianRupee, Plus, QrCode, Wallet } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, Field, Input, Select, Skeleton, Table, Td, Th } from '@/components/ui'
import { useAction, usePayables, useSuppliers } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { post } from '@/lib/api'
import { qrDataUrl, upiLink } from '@/lib/billing'
import { tr, useT } from '@/lib/i18n'
import type { SupplierDue } from '@/lib/types'
import { cn, money, shortDate } from '@/lib/utils'

const INVALIDATE = [['payables'], ['billing']]
const PAY_MODES = ['cash', 'upi', 'bank', 'cheque'] as const
const MODE_LABEL: Record<string, string> = { cash: 'Cash', upi: 'UPI', bank: 'Bank', cheque: 'Cheque' }

export function SupplierKhata() {
  const t = useT()
  const data = usePayables().data
  const { can } = useAuth()
  const [paying, setPaying] = useState<SupplierDue | null>(null)
  const [adding, setAdding] = useState(false)
  const s = data?.summary
  const cards = s
    ? [
        { label: t('Total to pay'), value: money(s.total), icon: <IndianRupee className="size-4" /> },
        { label: t('Overdue'), value: money(s.overdue), icon: <AlertTriangle className="size-4" />, tone: s.overdue ? 'text-critical' : '' },
        { label: t('Due in 7 days'), value: money(s.due_this_week), icon: <CalendarClock className="size-4" /> },
      ]
    : []
  return (
    <div className="space-y-4 p-4">
      <div className="grid gap-3 sm:grid-cols-3">
        {cards.map((c) => (
          <div key={c.label} className="rounded-lg border border-border p-3">
            <div className="flex items-center gap-1.5 text-xs text-muted">{c.icon} {c.label}</div>
            <div className={cn('mt-1 text-xl font-semibold tabular-nums', c.tone)}>{c.value}</div>
          </div>
        ))}
      </div>
      <Card>
        <CardHeader
          title={t('Supplier khata — whom you have to pay')}
          description={t('Received purchase orders are added here automatically, due after the supplier’s credit days.')}
          icon={<Factory className="size-4" />}
          action={can('manager') && <Button size="sm" variant="secondary" onClick={() => setAdding(true)}><Plus className="size-4" /> {t('Add purchase bill')}</Button>}
        />
        {!data ? <Skeleton className="m-5 h-40" /> : !data.suppliers.length ? <EmptyState title={t('Nothing to pay 🎉')} description={t('All supplier bills are paid.')} /> : (
          <Table>
            <thead><tr><Th>{t('Supplier')}</Th><Th>{t('Open bills')}</Th><Th>{t('Next due')}</Th><Th className="text-right">{t('Overdue')}</Th><Th className="text-right">{t('To pay')}</Th><Th className="text-right">{t('Actions')}</Th></tr></thead>
            <tbody>
              {data.suppliers.map((r) => (
                <tr key={r.supplier_id}>
                  <Td className="font-medium">{r.name}<div className="text-xs font-normal text-subtle">{r.phone} · {t('{n} days credit', { n: r.credit_days })}</div></Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      {r.bills.map((b) => (
                        <span key={b.id} title={`${shortDate(b.bill_date)} → ${shortDate(b.due_date)}`} className={cn('rounded border px-1.5 font-mono text-[11px]', b.overdue ? 'border-critical/40 text-critical' : 'border-border text-muted')}>
                          {b.bill_no ?? `#${b.id}`} · {money(b.balance)}
                        </span>
                      ))}
                    </div>
                  </Td>
                  <Td>{r.next_due ? shortDate(r.next_due) : '—'}</Td>
                  <Td className="text-right">{r.overdue ? <Badge tone="critical"><AlertTriangle className="size-3" /> {money(r.overdue)}</Badge> : <span className="text-subtle">—</span>}</Td>
                  <Td className="text-right font-semibold tabular-nums">{money(r.balance)}</Td>
                  <Td className="text-right">{can('manager') && <Button size="sm" onClick={() => setPaying(r)}><Wallet className="size-3.5" /> {t('Pay')}</Button>}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {paying && <PayDialog due={paying} onClose={() => setPaying(null)} />}
      {adding && <AddBillDialog onClose={() => setAdding(false)} />}
    </div>
  )
}

function PayDialog({ due, onClose }: { due: SupplierDue; onClose: () => void }) {
  const t = useT()
  const [amount, setAmount] = useState(String(due.balance))
  const [mode, setMode] = useState<(typeof PAY_MODES)[number]>(due.upi_id ? 'upi' : 'cash')
  const [reference, setReference] = useState('')
  const [qr, setQr] = useState<string | null>(null)
  const link = due.upi_id ? upiLink(due.upi_id, due.name, Number(amount) || 0, 'Supplier payment') : null
  useEffect(() => {
    let alive = true
    if (mode === 'upi' && link && Number(amount) > 0) void qrDataUrl(link, 180).then((url) => alive && setQr(url))
    return () => {
      alive = false
    }
  }, [mode, link, amount])
  const pay = useAction(() => post('/api/supplier-payments', { supplier_id: due.supplier_id, amount: Number(amount), mode, reference: reference || null }), {
    success: tr('Payment to {name} saved', { name: due.name }),
    invalidate: INVALIDATE,
    onSuccess: onClose,
  })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('Pay {name}', { name: due.name })} description={`${money(due.balance)} ${t('to pay')} · ${t('oldest bill is cleared first')}`} footer={<Button onClick={() => pay.mutate(undefined)} loading={pay.isPending} disabled={!(Number(amount) > 0)}><Wallet className="size-4" /> {t('Save payment')}</Button>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t('Amount')}><Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        <Field label={t('Mode')}><Select value={mode} onChange={(e) => setMode(e.target.value as (typeof PAY_MODES)[number])}>{PAY_MODES.map((m) => <option key={m} value={m}>{t(MODE_LABEL[m])}</option>)}</Select></Field>
        <Field label={t('UTR / cheque no. (optional)')} className="sm:col-span-2"><Input value={reference} onChange={(e) => setReference(e.target.value)} /></Field>
      </div>
      {mode === 'upi' && (qr ? (
        <div className="mt-3 grid place-items-center rounded-xl border border-border p-3">
          <img src={qr} alt={t('UPI QR')} className="size-44" />
          <div className="mt-1 flex items-center gap-1 text-xs text-muted"><QrCode className="size-3.5" /> {t('Scan with your UPI app to pay')} {due.upi_id}</div>
        </div>
      ) : !due.upi_id && <p className="mt-3 text-xs text-muted">{t("Add the supplier's UPI ID in Settings → Catalog to get a QR here.")}</p>)}
    </Dialog>
  )
}

function AddBillDialog({ onClose }: { onClose: () => void }) {
  const t = useT()
  const suppliers = useSuppliers().data
  const [form, setForm] = useState({ supplier_id: '', amount: '', bill_no: '', bill_date: '', due_date: '' })
  const add = useAction(
    () =>
      post('/api/supplier-bills', {
        supplier_id: Number(form.supplier_id),
        amount: Number(form.amount),
        bill_no: form.bill_no || null,
        bill_date: form.bill_date || null,
        due_date: form.due_date || null,
      }),
    { success: t('Purchase bill added'), invalidate: INVALIDATE, onSuccess: onClose },
  )
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={t('Add purchase bill')} description={t('A bill from a supplier that you will pay later (maal aaya, paise baad mein).')} footer={<Button onClick={() => add.mutate(undefined)} loading={add.isPending} disabled={!form.supplier_id || !(Number(form.amount) > 0)}>{t('Save')}</Button>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t('Supplier')} className="sm:col-span-2">
          <Select value={form.supplier_id} onChange={(e) => setForm({ ...form, supplier_id: e.target.value })}>
            <option value="">{t('Choose…')}</option>
            {suppliers?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </Field>
        <Field label={t('Amount (incl. GST)')}><Input type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></Field>
        <Field label={t('Supplier bill no.')}><Input value={form.bill_no} onChange={(e) => setForm({ ...form, bill_no: e.target.value })} /></Field>
        <Field label={t('Bill date')}><Input type="date" value={form.bill_date} onChange={(e) => setForm({ ...form, bill_date: e.target.value })} /></Field>
        <Field label={t('Due date')} hint={t('Blank = bill date + credit days')}><Input type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} /></Field>
      </div>
    </Dialog>
  )
}
