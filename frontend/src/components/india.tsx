/** India-specific UI: festival stock planner, GST report, next-festival banner. */
import { CalendarHeart, ChevronRight, Landmark, ShoppingCart, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { keys, useAction, useBillingProfile, useFestivalPlan, useFestivals, useGst } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { post } from '@/lib/api'
import { cn, IST, money, moneyCompact, number, shortDate, titleCase } from '@/lib/utils'
import { BarList } from './charts'
import { Badge, Button, Card, CardHeader, EmptyState, Segmented, Skeleton, Table, Td, Th } from './ui'
import { useT } from '@/lib/i18n'

const CATEGORY_LABEL: Record<string, string> = {
  grocery: 'Groceries & sweets', puja: 'Puja samagri', electronics: 'Electronics', home: 'Home & kitchen', beauty: 'Health & beauty',
  accessories: 'Accessories & gifts', toys: 'Toys', office: 'Office', sports: 'Sports',
}

export function FestivalPlanner() {
  const t = useT()
  const festivals = useFestivals()
  const [slug, setSlug] = useState<string | null>(null)
  const plan = useFestivalPlan(slug)
  const { can } = useAuth()
  const navigate = useNavigate()
  const order = useAction(() => post<unknown[]>('/api/india/festival-orders', { festival: plan.data?.festival?.slug }), {
    success: (r) => `Drafted ${r.length} festival PO(s) — one per supplier`,
    invalidate: [['purchase-orders'], keys.dashboard, ['festival-plan']],
    onSuccess: () => navigate('/purchase-orders'),
  })
  const f = plan.data?.festival
  const s = plan.data?.summary
  const shopState = useBillingProfile().data?.state

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        {shopState && <b className="text-fg">{t('Festivals for {state}', { state: shopState })}. </b>}
        {t("Festivals shown for your shop's state — change it in Settings → Shop details.")}
      </p>
      <div className="flex gap-3 overflow-x-auto pb-1">
        {festivals.data?.slice(0, 10).map((fest) => (
          <button
            key={fest.slug}
            onClick={() => setSlug(fest.slug)}
            className={cn(
              'min-w-40 shrink-0 rounded-xl border p-3 text-left transition',
              (f?.slug ?? '') === fest.slug ? 'border-brand bg-brand-soft' : 'border-border bg-surface hover:border-brand/40',
            )}
          >
            <div className="text-2xl">{fest.emoji}</div>
            <div className="mt-1 text-sm font-semibold">{fest.name}{fest.regional && <Badge tone="brand" className="ml-1.5 align-middle">{t('Regional')}</Badge>}</div>
            <div className="text-xs text-muted">{new Date(fest.date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: IST })}</div>
            <div className="mt-1 text-xs font-medium text-brand">{fest.days_away === 0 ? 'Today' : `in ${fest.days_away} days`}</div>
          </button>
        ))}
      </div>

      {plan.isLoading || !f ? (
        <Skeleton className="h-64" />
      ) : (
        <Card>
          <CardHeader
            title={`${f.emoji} ${f.name} stock-up plan`}
            description={`Buying window opens ${shortDate(f.buying_starts)} (${f.window_days} days before). ${f.note}`}
            icon={<CalendarHeart className="size-4" />}
            action={
              can('staff') && !!s?.products_to_order && (
                <Button onClick={() => order.mutate(undefined)} loading={order.isPending}>
                  <ShoppingCart className="size-4" /> Draft festival POs · {moneyCompact(s.order_value)}
                </Button>
              )
            }
          />
          <div className="grid gap-4 px-5 pb-4 md:grid-cols-4">
            {[
              ['Products affected', number(s?.products_affected)],
              ['Extra units expected', number(s?.extra_units)],
              ['Extra revenue', moneyCompact(s?.extra_revenue)],
              ['First order by', s?.earliest_order_by ? shortDate(s.earliest_order_by) : '—'],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-border p-3">
                <div className="text-xs text-muted">{label}</div>
                <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5 px-5 pb-4">
            {Object.entries(f.categories).map(([k, v]) => (
              <Badge key={k} tone="brand">{CATEGORY_LABEL[k] ?? titleCase(k)} ×{v}</Badge>
            ))}
          </div>
          {!plan.data?.items.length ? (
            <EmptyState title={t('No products in the affected categories')} />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>{t('Product')}</Th>
                  <Th>{t('Supplier')}</Th>
                  <Th className="text-right">{t('Lift')}</Th>
                  <Th className="text-right">{t('Extra units')}</Th>
                  <Th className="text-right">{t('Stock + on order')}</Th>
                  <Th className="text-right">{t('Order qty')}</Th>
                  <Th>{t('Order by')}</Th>
                </tr>
              </thead>
              <tbody>
                {plan.data.items.map((i) => (
                  <tr key={i.product_id} className={cn(!i.suggested_order_qty && 'opacity-60')}>
                    <Td><div className="font-medium">{i.name}</div><div className="font-mono text-xs text-subtle">{i.sku}</div></Td>
                    <Td className="text-muted">{i.supplier}</Td>
                    <Td className="text-right tabular-nums">×{i.uplift}</Td>
                    <Td className="text-right tabular-nums">+{number(i.extra_units)}</Td>
                    <Td className="text-right tabular-nums">{number(i.on_hand + i.on_order)}</Td>
                    <Td className="text-right font-medium tabular-nums">{i.suggested_order_qty ? number(i.suggested_order_qty) : '✓ covered'}</Td>
                    <Td>
                      {i.suggested_order_qty ? (
                        <span className={cn('inline-flex items-center gap-1 text-xs', i.urgent ? 'font-medium text-critical' : 'text-muted')}>
                          {i.urgent && <TriangleAlert className="size-3.5" />}
                          {shortDate(i.order_by)} {i.days_left_to_order <= 0 ? '(overdue)' : `(${i.days_left_to_order}d)`}
                        </span>
                      ) : (
                        <span className="text-xs text-subtle">—</span>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          <p className="px-5 py-3 text-xs text-subtle">
            Order-by = buying window start − supplier lead time. Quantities cover normal demand until the festival, the festival lift and safety stock, rounded to MOQ.
          </p>
        </Card>
      )}
    </div>
  )
}

export function GstPanel() {
  const t = useT()
  const [days, setDays] = useState<'30' | '90'>('30')
  const gst = useGst(Number(days))
  const g = gst.data
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">{t('GSTR-3B style estimate: output tax on sales vs input tax credit (ITC) on received purchases.')}</p>
        <Segmented size="sm" value={days} onChange={setDays} options={[{ value: '30', label: t('Last 30 days') }, { value: '90', label: t('Last 90 days') }]} />
      </div>
      {!g ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-3">
            <Card className="p-4"><div className="text-xs text-muted">{t('Output tax (on sales)')}</div><div className="mt-1 text-2xl font-semibold tabular-nums">{money(g.output_tax)}</div></Card>
            <Card className="p-4"><div className="text-xs text-muted">{t('Input tax credit')}</div><div className="mt-1 text-2xl font-semibold tabular-nums">{money(g.input_tax_credit)}</div></Card>
            <Card className="p-4">
              <div className="text-xs text-muted">{g.carry_forward_credit ? 'Credit carried forward' : 'Net GST payable'}</div>
              <div className="mt-1 text-2xl font-semibold tabular-nums">{money(g.carry_forward_credit || g.net_payable)}</div>
            </Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title={t('By GST slab')} icon={<Landmark className="size-4" />} />
              <Table>
                <thead><tr><Th>{t('Slab')}</Th><Th className="text-right">{t('Sales (taxable)')}</Th><Th className="text-right">{t('Output tax')}</Th><Th className="text-right">{t('Purchases')}</Th><Th className="text-right">{t('ITC')}</Th></tr></thead>
                <tbody>
                  {g.slabs.map((s) => (
                    <tr key={s.rate}>
                      <Td><Badge tone="info">{s.rate}%</Badge></Td>
                      <Td className="text-right tabular-nums">{moneyCompact(s.sales_taxable)}</Td>
                      <Td className="text-right tabular-nums">{moneyCompact(s.output_tax)}</Td>
                      <Td className="text-right tabular-nums">{moneyCompact(s.purchase_taxable)}</Td>
                      <Td className="text-right tabular-nums">{moneyCompact(s.input_tax)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Card>
            <Card>
              <CardHeader title={t('Output tax by slab')} />
              <div className="px-5 pb-5">
                <BarList items={g.slabs.map((s) => ({ key: String(s.rate), label: `${s.rate}% slab`, value: s.output_tax }))} format={moneyCompact} />
              </div>
            </Card>
          </div>
          <p className="text-xs text-subtle">{g.note}</p>
        </>
      )}
    </div>
  )
}

export function NextFestivalCard() {
  const t = useT()
  const plan = useFestivalPlan(null)
  const f = plan.data?.festival
  if (!f) return null
  const s = plan.data!.summary
  return (
    <Link to="/insights?tab=festival" className="group block h-full">
      <Card className="flex h-full items-center gap-4 border-warning/40 bg-gradient-to-r from-warning/10 to-transparent p-4 transition group-hover:border-warning">
        <div className="text-3xl">{f.emoji}</div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">
            {f.name} · {t('in {n} days', { n: f.days_away })} · {new Date(f.date).toLocaleDateString('en-IN', { day: 'numeric', month: 'long', timeZone: IST })}
          </div>
          <div className="text-sm text-muted">
            {s.products_to_order
              ? t('{n} products need extra stock (~{amount} extra sales)', { n: s.products_to_order, amount: moneyCompact(s.extra_revenue) }) + (s.earliest_order_by ? ` — ${t('first order by')} ${shortDate(s.earliest_order_by)}` : '')
              : t('Stock already covers the expected festival demand.')}
          </div>
        </div>
        <ChevronRight className="size-5 text-muted transition group-hover:translate-x-0.5" />
      </Card>
    </Link>
  )
}
