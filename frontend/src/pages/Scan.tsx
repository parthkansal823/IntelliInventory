import { Camera, CameraOff, Keyboard, Minus, Plus, ScanLine } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { StatusBadge } from '@/components/domain'
import { Button, Card, CardHeader, EmptyState, Input, PageHeader, Segmented, Select } from '@/components/ui'
import { keys, useAction, useWarehouses } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { useBarcodeScanner } from '@/hooks/useBarcodeScanner'
import { post } from '@/lib/api'
import type { StockStatus } from '@/lib/types'
import { cn, timeOnly } from '@/lib/utils'
import { useT } from '@/lib/i18n'

type Action = 'lookup' | 'receive' | 'sell' | 'return' | 'adjust'
interface ScanResult {
  product: { id: number; sku: string; name: string }
  on_hand: number
  status: StockStatus
  reorder_point: number
  warehouses: { code: string; quantity: number }[]
}

export default function Scan() {
  const t = useT()
  const { can } = useAuth()
  const warehouses = useWarehouses()
  const [action, setAction] = useState<Action>('lookup')
  const [qty, setQty] = useState(1)
  const [warehouse, setWarehouse] = useState<number | ''>('')
  const [code, setCode] = useState('')
  const [log, setLog] = useState<(ScanResult & { action: Action; qty: number; at: string })[]>([])

  const scan = useAction(
    (c: string) => post<ScanResult>('/api/inventory/scan', { code: c, action, quantity: action === 'adjust' ? qty : Math.abs(qty), warehouse_id: warehouse || undefined }),
    {
      success: (r) => (action === 'lookup' ? `${r.product.name}: ${r.on_hand} on hand` : `${r.product.name} → ${r.on_hand} on hand`),
      invalidate: action === 'lookup' ? [] : [keys.products, keys.dashboard, keys.alerts],
      onSuccess: (r) => setLog((l) => [{ ...r, action, qty, at: timeOnly(new Date()) }, ...l].slice(0, 20)),
    },
  )
  const { videoRef, active, error, start, stop } = useBarcodeScanner((c) => scan.mutate(c))
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (code.trim()) scan.mutate(code.trim())
    setCode('')
  }
  const latest = log[0]

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title={t('Scan mode')} description={t('Point the camera at a product QR / barcode — or type a SKU. Works great on phones (install as an app).')} />
      <div className="grid gap-4 md:grid-cols-2">
        <Card className="overflow-hidden">
          <div className="relative aspect-[4/3] bg-black">
            <video ref={videoRef} className={cn('size-full object-cover', !active && 'hidden')} muted playsInline />
            {!active && (
              <div className="absolute inset-0 grid place-items-center text-center text-white/70">
                <div>
                  <ScanLine className="mx-auto size-10" />
                  <p className="mt-2 text-sm">{error ?? 'Camera is off'}</p>
                </div>
              </div>
            )}
            {active && <div className="pointer-events-none absolute inset-8 rounded-2xl border-2 border-white/70 shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]" />}
          </div>
          <div className="flex gap-2 p-3">
            {active ? (
              <Button variant="secondary" className="flex-1" onClick={stop}><CameraOff className="size-4" /> {t('Stop camera')}</Button>
            ) : (
              <Button className="flex-1" onClick={start}><Camera className="size-4" /> {t('Start camera')}</Button>
            )}
          </div>
          <form onSubmit={submit} className="flex gap-2 border-t border-border p-3">
            <div className="relative flex-1">
              <Keyboard className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" />
              <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder={t('Barcode, SKU or name, e.g. ATA-105')} className="pl-9" />
            </div>
            <Button type="submit" loading={scan.isPending}>{t('Go')}</Button>
          </form>
        </Card>

        <div className="space-y-4">
          <Card className="space-y-4 p-4">
            <div>
              <div className="mb-1.5 text-xs font-medium text-muted">{t('Action')}</div>
              <Segmented
                value={action}
                onChange={setAction}
                size="sm"
                options={[
                  { value: 'lookup', label: t('Look up') },
                  ...(can('staff')
                    ? ([
                        { value: 'receive', label: t('Receive') },
                        { value: 'sell', label: t('Sell') },
                        { value: 'return', label: t('Return') },
                        { value: 'adjust', label: t('Adjust ±') },
                      ] as { value: Action; label: string }[])
                    : []),
                ]}
              />
            </div>
            {action !== 'lookup' && (
              <div className="flex flex-wrap items-end gap-3">
                <div>
                  <div className="mb-1.5 text-xs font-medium text-muted">{t('Quantity')}</div>
                  <div className="flex items-center gap-1">
                    <Button variant="secondary" size="icon" onClick={() => setQty((q) => q - 1)} aria-label={t('Decrease')}><Minus className="size-4" /></Button>
                    <Input type="number" value={qty} onChange={(e) => setQty(Number(e.target.value))} className="w-20 text-center" />
                    <Button variant="secondary" size="icon" onClick={() => setQty((q) => q + 1)} aria-label={t('Increase')}><Plus className="size-4" /></Button>
                  </div>
                </div>
                <div className="flex-1">
                  <div className="mb-1.5 text-xs font-medium text-muted">{t('Warehouse')}</div>
                  <Select value={warehouse} onChange={(e) => setWarehouse(e.target.value ? Number(e.target.value) : '')}>
                    <option value="">{t('Default (MAIN)')}</option>
                    {warehouses.data?.map((w) => <option key={w.id} value={w.id}>{w.code} — {w.name}</option>)}
                  </Select>
                </div>
              </div>
            )}
          </Card>

          <Card>
            <CardHeader title={t('Last scan')} />
            <div className="px-5 pb-5">
              {!latest ? (
                <EmptyState title={t('Nothing scanned yet')} description={t('Print product labels from the Inventory page to try it.')} />
              ) : (
                <div>
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="text-lg font-semibold">{latest.product.name}</div>
                      <div className="font-mono text-sm text-muted">{latest.product.sku}</div>
                    </div>
                    <StatusBadge status={latest.status} />
                  </div>
                  <div className="mt-4 text-4xl font-semibold tabular-nums">{latest.on_hand}<span className="ml-2 text-sm font-normal text-muted">on hand · ROP {latest.reorder_point}</span></div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {latest.warehouses.map((w) => <span key={w.code} className="rounded-md bg-surface-2 px-2 py-1 text-xs">{w.code}: <b>{w.quantity}</b></span>)}
                  </div>
                </div>
              )}
            </div>
          </Card>

          {log.length > 1 && (
            <Card>
              <CardHeader title={t('Session log')} />
              <ul className="divide-y divide-border px-5 pb-3 text-sm">
                {log.slice(1).map((l, i) => (
                  <li key={i} className="flex justify-between py-2">
                    <span><span className="text-subtle">{l.at}</span> · {l.product.sku} <span className="capitalize text-muted">{l.action}{l.action !== 'lookup' ? ` ${l.qty}` : ''}</span></span>
                    <span className="tabular-nums">{l.on_hand}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
