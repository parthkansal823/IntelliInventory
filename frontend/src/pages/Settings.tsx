import { Bot, Building2, Check, Keyboard, Landmark, Monitor, Moon, Plug, Plus, RefreshCw, Sparkles, Sun, Users } from 'lucide-react'
import { useState } from 'react'
import { Badge, Button, Card, CardHeader, CodeBlock, Dialog, Field, Input, PageHeader, Select, Skeleton, Switch, Table, Tabs, TabsContent, TabsList, TabsTrigger, Td, Th } from '@/components/ui'
import { keys, useAction, useAgents, useBillingProfile, useCategories, useGstSettings, useProducts, useSupplierScores, useSuppliers, useSystemInfo, useUsers, useWarehouses } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'
import { patch, post, put } from '@/lib/api'
import type { BusinessProfile, GstSettings, Role } from '@/lib/types'
import { cn, moneyCompact, number } from '@/lib/utils'

export default function SettingsPage() {
  const { can } = useAuth()
  return (
    <div>
      <PageHeader title="Settings" description="Business & GST, AI providers, integrations, catalog, people and preferences." />
      <Tabs defaultValue={new URLSearchParams(window.location.search).get('tab') ?? 'business'}>
        <TabsList>
          <TabsTrigger value="business"><Landmark className="size-4" /> Business & GST</TabsTrigger>
          <TabsTrigger value="ai"><Bot className="size-4" /> AI providers</TabsTrigger>
          <TabsTrigger value="integrations"><Plug className="size-4" /> Hermes & MCP</TabsTrigger>
          <TabsTrigger value="catalog"><Building2 className="size-4" /> Catalog</TabsTrigger>
          {can('admin') && <TabsTrigger value="users"><Users className="size-4" /> Users</TabsTrigger>}
          <TabsTrigger value="prefs"><Keyboard className="size-4" /> Preferences</TabsTrigger>
        </TabsList>
        <TabsContent value="business"><Business /></TabsContent>
        <TabsContent value="ai"><Providers /></TabsContent>
        <TabsContent value="integrations"><Integrations /></TabsContent>
        <TabsContent value="catalog"><Catalog /></TabsContent>
        <TabsContent value="users"><UsersAdmin /></TabsContent>
        <TabsContent value="prefs"><Preferences /></TabsContent>
      </Tabs>
    </div>
  )
}

function Business() {
  const settings = useGstSettings()
  const products = useProducts()
  const { can } = useAuth()
  const [slabText, setSlabText] = useState<string | null>(null)
  const invalidate = [['gst-settings'], ['gst'], ['festival-plan'], keys.products, ['purchase-orders']]
  const save = useAction((body: { gst_enabled?: boolean; slabs?: number[] }) => patch<GstSettings>('/api/india/settings', body), {
    success: 'GST settings saved',
    invalidate,
    onSuccess: () => setSlabText(null),
  })
  const fill = useAction((refresh_ai: boolean) => post<{ filled: number }>('/api/india/gst/autofill', { refresh_ai }), {
    success: (r) => (r.filled ? `AI filled HSN + GST for ${r.filled} product(s) — review the "AI" ones` : 'Nothing to fill — every product already has a GST rate'),
    invalidate,
  })
  if (!settings.data) return <Skeleton className="h-64" />
  const s = settings.data
  const text = slabText ?? s.slabs.join(', ')
  const parsed = text.split(/[\s,]+/).filter(Boolean).map(Number)
  const valid = parsed.length > 0 && parsed.every((n) => Number.isFinite(n) && n >= 0 && n <= 100)
  const missing = products.data?.filter((p) => p.gst_rate == null).length ?? 0
  const aiFilled = products.data?.filter((p) => p.gst_source === 'ai').length ?? 0
  const manager = can('manager')

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ShopProfile states={s.states} />
      <Card>
        <CardHeader title="GST registration" description="Optional — small shops below the GST threshold can switch it off. Nothing is lost; turn it back on any time." icon={<Landmark className="size-4" />} />
        <div className="space-y-4 px-5 pb-5">
          <div className="flex items-center justify-between gap-4 rounded-lg border border-border p-3">
            <div>
              <div className="text-sm font-medium">I am GST-registered</div>
              <div className="text-xs text-muted">{s.gst_enabled ? 'POs show CGST/SGST/IGST, e-way bill hints and the GST report.' : 'GST is hidden everywhere; PO totals are without tax.'}</div>
            </div>
            <Switch checked={s.gst_enabled} disabled={!manager || save.isPending} onCheckedChange={(v) => save.mutate({ gst_enabled: v })} label="GST registered" />
          </div>
          <Field label="GST slabs (%)" hint={<>Rates change? Edit the list — AI suggestions snap to these slabs. Default = GST 2.0 (from 22 Sep 2025): {s.default_slabs.join(', ')}.</>}>
            <div className="flex gap-2">
              <Input value={text} onChange={(e) => setSlabText(e.target.value)} disabled={!manager} placeholder="0, 3, 5, 18, 40" />
              {manager && (
                <Button variant="secondary" disabled={!valid || slabText === null} loading={save.isPending} onClick={() => save.mutate({ slabs: parsed })}>Save</Button>
              )}
            </div>
          </Field>
          <div className="flex flex-wrap gap-1.5">
            {s.slabs.map((r) => <Badge key={r} tone="info">{r}%</Badge>)}
            {manager && s.slabs.join() !== s.default_slabs.join() && (
              <button className="text-xs text-brand hover:underline" onClick={() => save.mutate({ slabs: s.default_slabs })}>Reset to GST 2.0 defaults</button>
            )}
          </div>
        </div>
      </Card>
      <Card>
        <CardHeader title="HSN & GST auto-fill" description="Add products without GST — the AI fills HSN code + rate from the product name later. Rates you type yourself are never overwritten." icon={<Sparkles className="size-4" />} />
        <div className="space-y-4 px-5 pb-5">
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-border p-3"><div className="text-xs text-muted">Products without GST</div><div className="mt-1 text-xl font-semibold tabular-nums">{number(missing)}</div></div>
            <div className="rounded-lg border border-border p-3"><div className="text-xs text-muted">Filled by AI (to review)</div><div className="mt-1 text-xl font-semibold tabular-nums">{number(aiFilled)}</div></div>
          </div>
          {manager && (
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => fill.mutate(false)} loading={fill.isPending && fill.variables === false} disabled={!missing}><Sparkles className="size-4" /> Fill missing with AI</Button>
              <Button variant="secondary" onClick={() => fill.mutate(true)} loading={fill.isPending && fill.variables === true}><RefreshCw className="size-4" /> Re-check AI-filled rates</Button>
            </div>
          )}
          <p className="text-xs text-subtle">Uses Hermes when it is running (free, local via Ollama), otherwise built-in rules for common Indian goods. Always confirm with your CA — the AI only suggests.</p>
        </div>
      </Card>
    </div>
  )
}

const PROFILE_FIELDS: { key: keyof BusinessProfile; label: string; placeholder?: string; hint?: string }[] = [
  { key: 'name', label: 'Shop / business name' },
  { key: 'phone', label: 'Phone', placeholder: '98200 12345' },
  { key: 'address', label: 'Address (printed on bills)' },
  { key: 'gstin', label: 'GSTIN (optional)', placeholder: '27AAAAA0000A1Z5', hint: 'Your state is taken from the GSTIN.' },
  { key: 'upi_id', label: 'UPI ID for payments', placeholder: 'yourshop@okaxis', hint: 'Bills show a QR with the exact amount — money goes straight to your bank, no gateway fee.' },
  { key: 'invoice_prefix', label: 'Bill number prefix', placeholder: 'INV', hint: 'Bills are numbered INV/26-27/00001 — a new series every financial year.' },
  { key: 'email', label: 'Email' },
  { key: 'terms', label: 'Footer / terms' },
]

function ShopProfile({ states }: { states: string[] }) {
  const profile = useBillingProfile()
  const { can } = useAuth()
  const [draft, setDraft] = useState<Partial<BusinessProfile>>({})
  const save = useAction(() => patch<BusinessProfile>('/api/billing/profile', draft), {
    success: 'Shop details saved',
    invalidate: [['billing']],
    onSuccess: () => setDraft({}),
  })
  if (!profile.data) return <Skeleton className="h-64 lg:col-span-2" />
  const value = (k: keyof BusinessProfile) => draft[k] ?? profile.data[k] ?? ''
  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title="Shop details"
        description="Printed on every bill and used for the UPI QR."
        icon={<Building2 className="size-4" />}
        action={can('manager') && <Button size="sm" disabled={!Object.keys(draft).length} loading={save.isPending} onClick={() => save.mutate(undefined)}>Save</Button>}
      />
      <div className="grid gap-3 px-5 pb-5 md:grid-cols-2">
        {PROFILE_FIELDS.map((f) => (
          <Field key={f.key} label={f.label} hint={f.hint}>
            <Input value={value(f.key)} placeholder={f.placeholder} disabled={!can('manager')} onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} />
          </Field>
        ))}
        <Field label="State" hint="Same state as the customer → CGST + SGST, other state → IGST.">
          <Select value={value('state')} disabled={!can('manager')} onChange={(e) => setDraft({ ...draft, state: e.target.value })}>
            <option value="">—</option>
            {states.map((st) => <option key={st}>{st}</option>)}
          </Select>
        </Field>
      </div>
    </Card>
  )
}

function Providers() {
  const agents = useAgents()
  const { can } = useAuth()
  const setProvider = useAction((provider: string) => put<{ active_provider: string }>('/api/agents/provider', { provider }), {
    success: (r) => `Active provider: ${r.active_provider}`,
    invalidate: [keys.agents, keys.system],
  })
  if (!agents.data) return <Skeleton className="h-64" />
  const active = agents.data.active_provider
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-3">
        {agents.data.providers.map((p) => (
          <Card key={p.name} className={cn('p-5', active === p.name && 'ring-2 ring-brand')}>
            <div className="flex items-center justify-between">
              <div className="font-semibold">{p.label}</div>
              <div className="flex gap-1.5">
                {p.free && <Badge tone="good">free</Badge>}
                <Badge tone={p.configured ? 'brand' : 'neutral'}>{p.configured ? 'ready' : 'not set up'}</Badge>
              </div>
            </div>
            {p.model && <div className="mt-1 font-mono text-xs text-muted">{p.model}{p.base_url ? ` @ ${p.base_url}` : ''}</div>}
            <p className="mt-3 text-sm text-muted">{p.setup}</p>
            {active === p.name ? (
              <div className="mt-4 flex items-center gap-1.5 text-sm font-medium text-brand"><Check className="size-4" /> Active</div>
            ) : (
              can('manager') && <Button size="sm" variant="secondary" className="mt-4" disabled={!p.configured} onClick={() => setProvider.mutate(p.name)}>Use {p.label}</Button>
            )}
          </Card>
        ))}
      </div>
      {can('manager') && <Button variant="ghost" size="sm" onClick={() => setProvider.mutate('auto')}>Reset to auto (free-first)</Button>}
      <Card>
        <CardHeader title="Run Hermes locally for free" description="Nous Research Hermes models via Ollama — private, offline-capable, zero cost" />
        <div className="space-y-3 px-5 pb-5">
          <CodeBlock code={'# 1. install Ollama  →  https://ollama.com/download\nollama pull hermes3:3b       # Hermes 3 (3B) — ~2 GB, runs on any 8 GB laptop\nollama pull hermes3          # Hermes 3 (8B) — ~4.7 GB, smarter (16 GB RAM)\n# 2. keep Ollama running; IntelliInventory auto-detects it (no key, no cost)\n#    set HERMES_MODEL=hermes3:3b in .env to pick the small one'} />
          <p className="text-sm text-muted">Other hosts (Nous Portal, OpenRouter, vLLM, LM Studio) work too — set <code>HERMES_BASE_URL</code>, <code>HERMES_API_KEY</code> and <code>HERMES_MODEL</code> in <code>.env</code>. Servers without native tool calling can use <code>HERMES_TOOL_MODE=prompt</code> (Hermes <code>&lt;tool_call&gt;</code> XML format).</p>
        </div>
      </Card>
      <Card>
        <CardHeader title="Agent tools" description={`${agents.data.tools.length} tools shared by in-app agents and the MCP server`} />
        <div className="grid gap-2 px-5 pb-5 md:grid-cols-2">
          {agents.data.tools.map((t) => (
            <div key={t.name} className="rounded-lg border border-border p-3">
              <div className="flex items-center gap-1.5">
                <code className="text-sm font-medium">{t.name}</code>
                {t.requires_approval && <Badge tone="warning">approval</Badge>}
                {t.mutates && !t.requires_approval && <Badge tone="info">write</Badge>}
              </div>
              <p className="mt-1 line-clamp-2 text-xs text-muted">{t.description}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}

function Integrations() {
  const info = useSystemInfo()
  const origin = typeof window !== 'undefined' ? window.location.origin.replace('5173', '8000') : 'http://localhost:8000'
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="lg:col-span-2">
        <CardHeader title="Hermes Agent (Nous Research)" description="Give your Hermes Agent the whole inventory toolset — then chat with it from the terminal, Telegram, Discord, Slack or WhatsApp via the Hermes gateway." />
        <div className="grid gap-4 px-5 pb-5 md:grid-cols-2">
          <div>
            <div className="mb-1.5 text-xs font-medium text-muted">1 · Install the pack (plugin with guardrail hooks, gateway audit hook, skill)</div>
            <CodeBlock code={'./integrations/hermes/install.sh'} />
            <div className="mt-3 mb-1.5 text-xs font-medium text-muted">2 · ~/.hermes/config.yaml</div>
            <CodeBlock code={`mcp_servers:\n  intelliinventory:\n    url: "${origin}/mcp/"\n    headers:\n      Authorization: "Bearer hermes-dev-token"\n    timeout: 60`} />
          </div>
          <div>
            <div className="mb-1.5 text-xs font-medium text-muted">…or run it over stdio (no server needed)</div>
            <CodeBlock code={`mcp_servers:\n  intelliinventory:\n    command: "uv"\n    args: ["run", "--directory", "/path/to/IntelliInventory/backend",\n           "python", "-m", "app.mcp_server"]`} />
            <p className="mt-3 text-sm text-muted">Tools appear in Hermes as <code>mcp_intelliinventory_*</code>. Write tools still route through IntelliInventory's approval queue, and the plugin forwards every call to this app's audit trail.</p>
          </div>
        </div>
      </Card>
      <Card>
        <CardHeader title="Other MCP clients" description="Cursor, VS Code, Continue, LM Studio… any MCP client works (mcp.json)" />
        <div className="px-5 pb-5">
          <CodeBlock code={`{\n  "mcpServers": {\n    "intelliinventory": {\n      "url": "${origin}/mcp/",\n      "headers": { "Authorization": "Bearer hermes-dev-token" }\n    }\n  }\n}`} />
        </div>
      </Card>
      <Card>
        <CardHeader title="Endpoints" />
        <div className="space-y-2 px-5 pb-5 text-sm">
          <div className="flex justify-between"><span className="text-muted">MCP (HTTP)</span><code>{info.data?.mcp.http_url ?? '…'}</code></div>
          <div className="flex justify-between"><span className="text-muted">Event ingest</span><code>POST /api/integrations/events</code></div>
          <div className="flex justify-between"><span className="text-muted">Live events (SSE)</span><code>GET /api/events/stream</code></div>
          <div className="flex justify-between"><span className="text-muted">OpenAPI docs</span><a className="text-brand hover:underline" href={`${origin}/docs`} target="_blank" rel="noreferrer">/docs</a></div>
          <div className="flex justify-between"><span className="text-muted">Database</span><code>{info.data?.database}</code></div>
          <div className="flex justify-between"><span className="text-muted">Version</span><code>{info.data?.version}</code></div>
        </div>
      </Card>
    </div>
  )
}

function Catalog() {
  const warehouses = useWarehouses()
  const suppliers = useSupplierScores()
  const supplierInfo = new Map(useSuppliers().data?.map((s) => [s.id, s]))
  const states = useGstSettings().data?.states ?? []
  const categories = useCategories()
  const { can } = useAuth()
  const [dialog, setDialog] = useState<null | 'warehouse' | 'supplier' | 'category'>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const set = (k: string) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const create = useAction(
    () =>
      dialog === 'warehouse'
        ? post('/api/warehouses', { code: form.code, name: form.name, location: form.location, state: form.state || null })
        : dialog === 'supplier'
          ? post('/api/suppliers', {
              name: form.name,
              email: form.email || null,
              phone: form.phone || null,
              gstin: form.gstin || null,
              state: form.state || null,
              upi_id: form.upi || null,
              lead_time_days: Number(form.lead || 7),
            })
          : post('/api/categories', { name: form.name, color: form.color || '#6366f1' }),
    { success: 'Created', invalidate: [keys.warehouses, keys.suppliers, keys.suppliersScores, keys.categories], onSuccess: () => { setDialog(null); setForm({}) } },
  )

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Warehouses" action={can('manager') && <Button size="sm" variant="secondary" onClick={() => setDialog('warehouse')}><Plus className="size-3.5" /> Add</Button>} />
        <Table>
          <thead><tr><Th>Code</Th><Th>Name</Th><Th className="text-right">Units</Th><Th className="text-right">Value</Th></tr></thead>
          <tbody>{warehouses.data?.map((w) => <tr key={w.id}><Td className="font-mono text-xs">{w.code}</Td><Td>{w.name}<div className="text-xs text-subtle">{[w.location, w.state].filter(Boolean).join(' · ')}</div></Td><Td className="text-right tabular-nums">{number(w.units)}</Td><Td className="text-right tabular-nums">{moneyCompact(w.value)}</Td></tr>)}</tbody>
        </Table>
      </Card>
      <Card>
        <CardHeader title="Categories" action={can('manager') && <Button size="sm" variant="secondary" onClick={() => setDialog('category')}><Plus className="size-3.5" /> Add</Button>} />
        <div className="flex flex-wrap gap-2 px-5 pb-5">
          {categories.data?.map((c) => <span key={c.id} className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-sm"><span className="size-2.5 rounded-full" style={{ background: c.color }} />{c.name}</span>)}
        </div>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader title="Suppliers" action={can('manager') && <Button size="sm" variant="secondary" onClick={() => setDialog('supplier')}><Plus className="size-3.5" /> Add</Button>} />
        <Table>
          <thead><tr><Th>Supplier</Th><Th>Contact</Th><Th>GSTIN · State</Th><Th className="text-right">Lead time</Th><Th className="text-right">Rating</Th><Th>Grade</Th></tr></thead>
          <tbody>{suppliers.data?.map((s) => <tr key={s.id}><Td className="font-medium">{s.name}{supplierInfo.get(s.id)?.upi_id && <div className="font-mono text-xs text-subtle">UPI {supplierInfo.get(s.id)?.upi_id}</div>}</Td><Td className="text-xs text-muted">{s.email}<br />{s.phone}</Td><Td className="text-xs"><div className="font-mono">{supplierInfo.get(s.id)?.gstin ?? '—'}</div><div className="text-muted">{supplierInfo.get(s.id)?.state}</div></Td><Td className="text-right tabular-nums">{s.promised_lead_time}d</Td><Td className="text-right tabular-nums">{s.rating.toFixed(1)}</Td><Td><Badge tone={s.grade === 'A' ? 'good' : s.grade === 'B' ? 'info' : 'warning'}>{s.grade}</Badge></Td></tr>)}</tbody>
        </Table>
      </Card>
      <Dialog open={!!dialog} onOpenChange={(o) => !o && setDialog(null)} title={`Add ${dialog}`} footer={<Button onClick={() => create.mutate(undefined)} loading={create.isPending}>Create</Button>}>
        <div className="grid gap-3">
          {dialog === 'warehouse' && <Field label="Code"><Input value={form.code ?? ''} onChange={set('code')} placeholder="WEST" /></Field>}
          <Field label="Name"><Input value={form.name ?? ''} onChange={set('name')} /></Field>
          {dialog === 'warehouse' && <Field label="Location"><Input value={form.location ?? ''} onChange={set('location')} placeholder="Bhiwandi, Mumbai" /></Field>}
          {(dialog === 'warehouse' || dialog === 'supplier') && (
            <Field label="State" hint={dialog === 'supplier' ? 'Filled from the GSTIN when you enter one. Same state as your warehouse → CGST + SGST, otherwise IGST.' : 'Decides CGST + SGST vs IGST on purchase orders.'}>
              <Select value={form.state ?? ''} onChange={set('state')}>
                <option value="">—</option>
                {states.map((st) => <option key={st}>{st}</option>)}
                {dialog === 'supplier' && <option>Outside India</option>}
              </Select>
            </Field>
          )}
          {dialog === 'supplier' && (
            <>
              <Field label="Phone" hint="Indian numbers get +91 automatically; foreign numbers start with + and the country code."><Input value={form.phone ?? ''} onChange={set('phone')} placeholder="98200 12345 or +971 50 123 4567" /></Field>
              <Field label="GSTIN (optional)"><Input value={form.gstin ?? ''} onChange={set('gstin')} placeholder="27AAPFU0939F1ZV" className="font-mono uppercase" maxLength={15} /></Field>
              <Field label="UPI ID (optional)" hint="Purchase orders show a scan-to-pay QR for this UPI ID."><Input value={form.upi ?? ''} onChange={set('upi')} placeholder="supplier@okhdfcbank" /></Field>
              <Field label="Email"><Input value={form.email ?? ''} onChange={set('email')} /></Field>
              <Field label="Lead time (days)"><Input type="number" value={form.lead ?? '7'} onChange={set('lead')} /></Field>
            </>
          )}
          {dialog === 'category' && <Field label="Color"><Input type="color" value={form.color ?? '#6366f1'} onChange={set('color')} className="h-10 p-1" /></Field>}
        </div>
      </Dialog>
    </div>
  )
}

function UsersAdmin() {
  const users = useUsers()
  const { user: me } = useAuth()
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ email: '', name: '', role: 'staff' as Role, password: '' })
  const update = useAction(({ id, ...body }: { id: number; role?: Role; is_active?: boolean }) => patch(`/api/users/${id}`, body), { success: 'User updated', invalidate: [keys.users] })
  const create = useAction(() => post('/api/users', form), { success: 'User created', invalidate: [keys.users], onSuccess: () => setAdding(false) })
  return (
    <Card>
      <CardHeader title="Users & roles" description="viewer (read-only) · staff (operate) · manager (approve) · admin (everything)" action={<Button size="sm" onClick={() => setAdding(true)}><Plus className="size-3.5" /> Invite</Button>} />
      <Table>
        <thead><tr><Th>Name</Th><Th>Email</Th><Th>Role</Th><Th>Status</Th></tr></thead>
        <tbody>
          {users.data?.map((u) => (
            <tr key={u.id}>
              <Td className="font-medium">{u.name}</Td>
              <Td className="text-muted">{u.email}</Td>
              <Td>
                <Select value={u.role} onChange={(e) => update.mutate({ id: u.id, role: e.target.value as Role })} disabled={u.id === me?.id} className="h-8 w-32 text-xs">
                  {['viewer', 'staff', 'manager', 'admin'].map((r) => <option key={r} value={r}>{r}</option>)}
                </Select>
              </Td>
              <Td>
                <button disabled={u.id === me?.id} onClick={() => update.mutate({ id: u.id, is_active: !u.is_active })}>
                  <Badge tone={u.is_active ? 'good' : 'neutral'}>{u.is_active ? 'active' : 'disabled'}</Badge>
                </button>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <Dialog open={adding} onOpenChange={setAdding} title="Invite user" footer={<Button onClick={() => create.mutate(undefined)} loading={create.isPending}>Create user</Button>}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Email"><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Role"><Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>{['viewer', 'staff', 'manager', 'admin'].map((r) => <option key={r}>{r}</option>)}</Select></Field>
          <Field label="Temporary password"><Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
        </div>
      </Dialog>
    </Card>
  )
}

function Preferences() {
  const { theme, setTheme } = useTheme()
  const shortcuts = [
    ['⌘K / Ctrl K', 'Command palette — search, navigate, ask Copilot'],
    ['/', 'Open search'],
    ['g d · g i · g c', 'Go to Dashboard · Inventory · Copilot'],
    ['g p · g n · g s', 'Purchase orders · Insights · Scan'],
    ['g o · g a · g t', 'Cycle counts · Automation · Settings'],
    ['Enter / Shift+Enter', 'Send / new line in chat'],
  ]
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Appearance" />
        <div className="flex gap-2 px-5 pb-5">
          {([['light', Sun], ['dark', Moon], ['system', Monitor]] as const).map(([t, Icon]) => (
            <button key={t} onClick={() => setTheme(t)} className={cn('flex flex-1 flex-col items-center gap-2 rounded-xl border p-4 text-sm capitalize transition', theme === t ? 'border-brand bg-brand-soft text-brand' : 'border-border hover:bg-surface-2')}>
              <Icon className="size-5" />
              {t}
            </button>
          ))}
        </div>
      </Card>
      <Card>
        <CardHeader title="Keyboard shortcuts" />
        <ul className="divide-y divide-border px-5 pb-4 text-sm">
          {shortcuts.map(([k, d]) => <li key={k} className="flex justify-between gap-4 py-2"><code className="text-xs">{k}</code><span className="text-right text-muted">{d}</span></li>)}
        </ul>
      </Card>
    </div>
  )
}
