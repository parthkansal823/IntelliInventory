import { ClipboardCheck, ClipboardList, EyeOff, Plus, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, Field, Input, PageHeader, Select, Skeleton, Switch, Table, Td, Th } from '@/components/ui'
import { keys, useAction, useCount, useCounts, useWarehouses } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { post, put } from '@/lib/api'
import type { CycleCountSummary } from '@/lib/types'
import { cn, money, pct, relativeTime } from '@/lib/utils'

export default function Counts() {
  const counts = useCounts()
  const { can } = useAuth()
  const [selected, setSelected] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)
  const id = selected ?? counts.data?.find((c) => c.status === 'open')?.id ?? counts.data?.[0]?.id ?? null

  return (
    <div>
      <PageHeader
        title="Cycle counts"
        description="Count a slice of stock, compare with the system, post variances as audited adjustments."
        actions={can('staff') && <Button onClick={() => setCreating(true)}><Plus className="size-4" /> New count</Button>}
      />
      <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
        <Card className="h-fit">
          <CardHeader title="Count sheets" />
          {counts.isLoading ? <Skeleton className="m-4 h-32" /> : !counts.data?.length ? (
            <EmptyState icon={<ClipboardList className="size-5" />} title="No counts yet" description="Start one, or ask the Auditor agent." />
          ) : (
            <ul className="space-y-1 px-2 pb-2">
              {counts.data.map((c) => (
                <li key={c.id}>
                  <button onClick={() => setSelected(c.id)} className={cn('w-full rounded-lg px-3 py-2 text-left transition', c.id === id ? 'bg-brand-soft' : 'hover:bg-surface-2')}>
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs font-medium">{c.number}</span>
                      <Badge tone={c.status === 'open' ? 'warning' : 'good'}>{c.status}</Badge>
                    </div>
                    <div className="mt-0.5 text-xs text-muted">{c.warehouse.code} · scope {c.scope} · {c.progress.counted}/{c.progress.total} · {relativeTime(c.created_at)}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {id ? <CountSheet id={id} /> : <Card><EmptyState title="Select or create a count" /></Card>}
      </div>
      <NewCountDialog open={creating} onOpenChange={setCreating} onCreated={(c) => setSelected(c.id)} />
    </div>
  )
}

function CountSheet({ id }: { id: number }) {
  const { data: count } = useCount(id)
  const { can } = useAuth()
  const [values, setValues] = useState<Record<number, string>>({})
  const [blind, setBlind] = useState(false)

  useEffect(() => {
    if (count?.lines) setValues(Object.fromEntries(count.lines.map((l) => [l.id, l.counted == null ? '' : String(l.counted)])))
  }, [count])

  const save = useAction(
    () => put<CycleCountSummary>(`/api/counts/${id}`, { counts: Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v === '' ? null : Number(v)])) }),
    { success: 'Counts saved', invalidate: [keys.counts, keys.count(id)] },
  )
  const postCount = useAction(() => post<CycleCountSummary>(`/api/counts/${id}/post`), {
    success: (c) => `${c.number} posted — net variance ${c.net_variance_units} units`,
    invalidate: [keys.counts, keys.count(id), keys.products, keys.dashboard],
  })

  if (!count?.lines) return <Card><Skeleton className="m-5 h-64" /></Card>
  const open = count.status === 'open'

  return (
    <Card>
      <CardHeader
        title={`${count.number} · ${count.warehouse.name}`}
        description={`Scope ${count.scope} · created by ${count.created_by.replace('user:', '').replace('agent:', 'agent ')} · accuracy ${pct(count.accuracy_pct)}`}
        action={
          open && (
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-2 text-xs text-muted"><EyeOff className="size-3.5" /> Blind count <Switch checked={blind} onCheckedChange={setBlind} label="Blind count" /></label>
              <Button size="sm" variant="secondary" onClick={() => save.mutate(undefined)} loading={save.isPending}><Save className="size-3.5" /> Save</Button>
              {can('manager') && (
                <Button size="sm" onClick={async () => { await save.mutateAsync(undefined); postCount.mutate(undefined) }} loading={postCount.isPending}>
                  <ClipboardCheck className="size-3.5" /> Post variances
                </Button>
              )}
            </div>
          )
        }
      />
      <div className="flex gap-6 px-5 pb-3 text-sm">
        <span>Progress <b>{count.progress.counted}/{count.progress.total}</b></span>
        <span>Net variance <b className={cn(count.net_variance_units < 0 && 'text-critical')}>{count.net_variance_units}</b> units</span>
        <span>Value <b className={cn(count.net_variance_value < 0 && 'text-critical')}>{money(count.net_variance_value)}</b></span>
      </div>
      <Table>
        <thead>
          <tr>
            <Th>SKU</Th>
            <Th>Product</Th>
            <Th className="text-right">Expected</Th>
            <Th className="w-32">Counted</Th>
            <Th className="text-right">Variance</Th>
          </tr>
        </thead>
        <tbody>
          {count.lines.map((l) => {
            const v = values[l.id]
            const variance = v === '' || v == null ? null : Number(v) - l.expected
            return (
              <tr key={l.id}>
                <Td className="font-mono text-xs">{l.sku}</Td>
                <Td>{l.name}</Td>
                <Td className="text-right tabular-nums">{blind && open ? '•••' : l.expected}</Td>
                <Td>
                  {open ? (
                    <Input type="number" min={0} value={v ?? ''} onChange={(e) => setValues((s) => ({ ...s, [l.id]: e.target.value }))} className="h-8 text-right" />
                  ) : (
                    <span className="tabular-nums">{l.counted ?? '—'}</span>
                  )}
                </Td>
                <Td className={cn('text-right font-medium tabular-nums', variance ? (variance < 0 ? 'text-critical' : 'text-good') : 'text-subtle')}>
                  {blind && open ? '' : variance == null ? '—' : `${variance > 0 ? '+' : ''}${variance}`}
                </Td>
              </tr>
            )
          })}
        </tbody>
      </Table>
    </Card>
  )
}

function NewCountDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (o: boolean) => void; onCreated: (c: CycleCountSummary) => void }) {
  const warehouses = useWarehouses()
  const [warehouse, setWarehouse] = useState<number | ''>('')
  const [scope, setScope] = useState('A')
  const create = useAction(() => post<CycleCountSummary>('/api/counts', { warehouse_id: warehouse || warehouses.data?.[0]?.id, scope }), {
    success: (c) => `Opened ${c.number} with ${c.progress.total} lines`,
    invalidate: [keys.counts],
    onSuccess: (c) => { onCreated(c); onOpenChange(false) },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="New cycle count" description="Snapshots expected quantities for the chosen slice of stock."
      footer={<Button onClick={() => create.mutate(undefined)} loading={create.isPending}>Create count sheet</Button>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Warehouse">
          <Select value={warehouse} onChange={(e) => setWarehouse(Number(e.target.value))}>
            {warehouses.data?.map((w) => <option key={w.id} value={w.id}>{w.code} — {w.name}</option>)}
          </Select>
        </Field>
        <Field label="Scope" hint="A-items first: highest value, count most often">
          <Select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="A">Class A items</option>
            <option value="B">Class B items</option>
            <option value="C">Class C items</option>
            <option value="all">Everything in the warehouse</option>
          </Select>
        </Field>
      </div>
    </Dialog>
  )
}
