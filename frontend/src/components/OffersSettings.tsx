/** Settings → Offers & loyalty. Everything is optional and OFF until the shop owner switches it on. */
import { Gift, Plus, Star, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Button, Card, CardHeader, Field, Input, Select, Skeleton, Switch } from '@/components/ui'
import { useAction, useCategories, useOffers, useProducts } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { put } from '@/lib/api'
import { useT } from '@/lib/i18n'
import type { Offer, OffersConfig, OfferType } from '@/lib/types'

const TYPE_LABEL: Record<OfferType, string> = {
  bill_percent: '% off on the whole bill',
  buy_x_get_y: 'Buy X get Y free',
  item_percent: '% off an item or category',
}
const blank = (type: OfferType): Offer =>
  type === 'bill_percent'
    ? { type, label: '', active: true, min_amount: 500, percent: 5 }
    : type === 'buy_x_get_y'
      ? { type, label: '', active: true, sku: '', buy: 2, free: 1 }
      : { type, label: '', active: true, category: '', sku: '', percent: 10 }

export function OffersSettings() {
  const t = useT()
  const cfg = useOffers().data
  const { can } = useAuth()
  if (!cfg) return <Skeleton className="h-40" />
  return <OffersForm key={JSON.stringify(cfg)} initial={cfg} canEdit={can('manager')} t={t} />
}

function OffersForm({ initial, canEdit, t }: { initial: OffersConfig; canEdit: boolean; t: ReturnType<typeof useT> }) {
  const [cfg, setCfg] = useState(initial)
  const [newType, setNewType] = useState<OfferType>('bill_percent')
  const products = useProducts().data
  const categories = useCategories().data
  const save = useAction(() => put<OffersConfig>('/api/billing/offers', cfg), { success: t('Offers & loyalty saved'), invalidate: [['billing', 'offers']] })
  const setOffer = (i: number, patch: Partial<Offer>) => setCfg({ ...cfg, offers: cfg.offers.map((o, j) => (j === i ? { ...o, ...patch } : o)) })
  const dirty = JSON.stringify(cfg) !== JSON.stringify(initial)

  return (
    <Card>
      <CardHeader
        title={t('Offers & loyalty (optional)')}
        description={t('Schemes like "5% off above ₹500" or "buy 2 get 1", and points for regular customers. Off by default.')}
        icon={<Gift className="size-4" />}
        action={<Switch checked={cfg.enabled} onCheckedChange={(v) => setCfg({ ...cfg, enabled: v })} label={t('Offers & loyalty on')} disabled={!canEdit} />}
      />
      {cfg.enabled && (
        <div className="space-y-5 px-5 pb-5">
          <div className="rounded-lg border border-border p-3">
            <label className="flex items-center gap-2 text-sm font-medium">
              <Switch checked={cfg.loyalty.enabled} onCheckedChange={(v) => setCfg({ ...cfg, loyalty: { ...cfg.loyalty, enabled: v } })} label={t('Loyalty points')} disabled={!canEdit} />
              <Star className="size-4 text-warning" /> {t('Loyalty points for customers')}
            </label>
            {cfg.loyalty.enabled && (
              <div className="mt-3 grid gap-2 sm:grid-cols-3">
                <Field label={t('Points per ₹100')}><Input type="number" min={0} step="0.5" value={cfg.loyalty.earn_per_100} onChange={(e) => setCfg({ ...cfg, loyalty: { ...cfg.loyalty, earn_per_100: Number(e.target.value) } })} /></Field>
                <Field label={t('1 point = ₹')}><Input type="number" min={0.01} step="0.25" value={cfg.loyalty.point_value} onChange={(e) => setCfg({ ...cfg, loyalty: { ...cfg.loyalty, point_value: Number(e.target.value) } })} /></Field>
                <Field label={t('Min points to use')}><Input type="number" min={0} value={cfg.loyalty.min_redeem} onChange={(e) => setCfg({ ...cfg, loyalty: { ...cfg.loyalty, min_redeem: Number(e.target.value) } })} /></Field>
              </div>
            )}
          </div>

          <div className="space-y-2">
            <div className="text-sm font-medium">{t('Offers')}</div>
            {!cfg.offers.length && <p className="text-xs text-muted">{t('No offers yet. Add one below.')}</p>}
            {cfg.offers.map((o, i) => (
              <div key={i} className="grid items-end gap-2 rounded-lg border border-border p-3 sm:grid-cols-[1.4fr_1fr_1fr_1fr_auto]">
                <Field label={t(TYPE_LABEL[o.type])}><Input value={o.label} placeholder={t('Name shown on the bill (optional)')} onChange={(e) => setOffer(i, { label: e.target.value })} /></Field>
                {o.type === 'bill_percent' && (
                  <>
                    <Field label={t('Bill above ₹')}><Input type="number" value={o.min_amount ?? 0} onChange={(e) => setOffer(i, { min_amount: Number(e.target.value) })} /></Field>
                    <Field label={t('% off')}><Input type="number" value={o.percent ?? 0} onChange={(e) => setOffer(i, { percent: Number(e.target.value) })} /></Field>
                    <div />
                  </>
                )}
                {o.type === 'buy_x_get_y' && (
                  <>
                    <Field label={t('Item')}>
                      <Select value={o.sku ?? ''} onChange={(e) => setOffer(i, { sku: e.target.value })}>
                        <option value="">{t('Choose…')}</option>
                        {products?.map((p) => <option key={p.id} value={p.sku}>{p.name}</option>)}
                      </Select>
                    </Field>
                    <Field label={t('Buy')}><Input type="number" min={1} value={o.buy ?? 2} onChange={(e) => setOffer(i, { buy: Number(e.target.value) })} /></Field>
                    <Field label={t('Free')}><Input type="number" min={1} value={o.free ?? 1} onChange={(e) => setOffer(i, { free: Number(e.target.value) })} /></Field>
                  </>
                )}
                {o.type === 'item_percent' && (
                  <>
                    <Field label={t('Category')}>
                      <Select value={o.category ?? ''} onChange={(e) => setOffer(i, { category: e.target.value, sku: '' })}>
                        <option value="">—</option>
                        {categories?.map((c) => <option key={c.id}>{c.name}</option>)}
                      </Select>
                    </Field>
                    <Field label={t('or item')}>
                      <Select value={o.sku ?? ''} onChange={(e) => setOffer(i, { sku: e.target.value, category: '' })}>
                        <option value="">—</option>
                        {products?.map((p) => <option key={p.id} value={p.sku}>{p.name}</option>)}
                      </Select>
                    </Field>
                    <Field label={t('% off')}><Input type="number" value={o.percent ?? 0} onChange={(e) => setOffer(i, { percent: Number(e.target.value) })} /></Field>
                  </>
                )}
                <div className="flex items-center gap-1 pb-1">
                  <Switch checked={o.active} onCheckedChange={(v) => setOffer(i, { active: v })} label={t('Active')} disabled={!canEdit} />
                  <Button size="icon" variant="ghost" className="size-8" aria-label={t('Delete')} onClick={() => setCfg({ ...cfg, offers: cfg.offers.filter((_, j) => j !== i) })} disabled={!canEdit}><Trash2 className="size-4" /></Button>
                </div>
              </div>
            ))}
            {canEdit && (
              <div className="flex flex-wrap items-center gap-2">
                <Select value={newType} onChange={(e) => setNewType(e.target.value as OfferType)} className="w-64">
                  {(Object.keys(TYPE_LABEL) as OfferType[]).map((k) => <option key={k} value={k}>{t(TYPE_LABEL[k])}</option>)}
                </Select>
                <Button variant="secondary" size="sm" onClick={() => setCfg({ ...cfg, offers: [...cfg.offers, blank(newType)] })}><Plus className="size-4" /> {t('Add offer')}</Button>
              </div>
            )}
          </div>
        </div>
      )}
      {canEdit && (
        <div className="flex justify-end border-t border-border px-5 py-3">
          <Button onClick={() => save.mutate(undefined)} loading={save.isPending} disabled={!dirty}>{t('Save offers')}</Button>
        </div>
      )}
    </Card>
  )
}
