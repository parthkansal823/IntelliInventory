import { Bot, Building2, Check, Keyboard, Monitor, Moon, Plug, Plus, Sun, Users } from 'lucide-react'
import { useState } from 'react'
import { Badge, Button, Card, CardHeader, CodeBlock, Dialog, Field, Input, PageHeader, Select, Skeleton, Table, Tabs, TabsContent, TabsList, TabsTrigger, Td, Th } from '@/components/ui'
import { keys, useAction, useAgents, useCategories, useSupplierScores, useSystemInfo, useUsers, useWarehouses } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'
import { patch, post, put } from '@/lib/api'
import type { Role } from '@/lib/types'
import { cn, moneyCompact, number } from '@/lib/utils'

export default function SettingsPage() {
  const { can } = useAuth()
  return (
    <div>
      <PageHeader title="Settings" description="AI providers, integrations, catalog, people and preferences." />
      <Tabs defaultValue="ai">
        <TabsList>
          <TabsTrigger value="ai"><Bot className="size-4" /> AI providers</TabsTrigger>
          <TabsTrigger value="integrations"><Plug className="size-4" /> Hermes & MCP</TabsTrigger>
          <TabsTrigger value="catalog"><Building2 className="size-4" /> Catalog</TabsTrigger>
          {can('admin') && <TabsTrigger value="users"><Users className="size-4" /> Users</TabsTrigger>}
          <TabsTrigger value="prefs"><Keyboard className="size-4" /> Preferences</TabsTrigger>
        </TabsList>
        <TabsContent value="ai"><Providers /></TabsContent>
        <TabsContent value="integrations"><Integrations /></TabsContent>
        <TabsContent value="catalog"><Catalog /></TabsContent>
        <TabsContent value="users"><UsersAdmin /></TabsContent>
        <TabsContent value="prefs"><Preferences /></TabsContent>
      </Tabs>
    </div>
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
          <CodeBlock code={'# 1. install Ollama  →  https://ollama.com/download\nollama pull hermes3          # Hermes 3 (8B) — ~4.7 GB\n# 2. keep Ollama running; IntelliInventory auto-detects it (no key needed)\n# optional: a larger model\nollama pull hermes3:70b'} />
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
        <CardHeader title="Claude Code / Claude Desktop / Cursor" description="Any MCP client works" />
        <div className="px-5 pb-5">
          <CodeBlock code={`claude mcp add intelliinventory -- uv run --directory backend python -m app.mcp_server\n\n# or HTTP\nclaude mcp add --transport http intelliinventory ${origin}/mcp/ \\\n  --header "Authorization: Bearer hermes-dev-token"`} />
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
  const categories = useCategories()
  const { can } = useAuth()
  const [dialog, setDialog] = useState<null | 'warehouse' | 'supplier' | 'category'>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const set = (k: string) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const create = useAction(
    () =>
      dialog === 'warehouse'
        ? post('/api/warehouses', { code: form.code, name: form.name, location: form.location })
        : dialog === 'supplier'
          ? post('/api/suppliers', { name: form.name, email: form.email, lead_time_days: Number(form.lead || 7) })
          : post('/api/categories', { name: form.name, color: form.color || '#6366f1' }),
    { success: 'Created', invalidate: [keys.warehouses, keys.suppliers, keys.suppliersScores, keys.categories], onSuccess: () => { setDialog(null); setForm({}) } },
  )

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Warehouses" action={can('manager') && <Button size="sm" variant="secondary" onClick={() => setDialog('warehouse')}><Plus className="size-3.5" /> Add</Button>} />
        <Table>
          <thead><tr><Th>Code</Th><Th>Name</Th><Th className="text-right">Units</Th><Th className="text-right">Value</Th></tr></thead>
          <tbody>{warehouses.data?.map((w) => <tr key={w.id}><Td className="font-mono text-xs">{w.code}</Td><Td>{w.name}<div className="text-xs text-subtle">{w.location}</div></Td><Td className="text-right tabular-nums">{number(w.units)}</Td><Td className="text-right tabular-nums">{moneyCompact(w.value)}</Td></tr>)}</tbody>
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
          <thead><tr><Th>Supplier</Th><Th>Contact</Th><Th className="text-right">Lead time</Th><Th className="text-right">Rating</Th><Th>Grade</Th></tr></thead>
          <tbody>{suppliers.data?.map((s) => <tr key={s.id}><Td className="font-medium">{s.name}</Td><Td className="text-xs text-muted">{s.email}<br />{s.phone}</Td><Td className="text-right tabular-nums">{s.promised_lead_time}d</Td><Td className="text-right tabular-nums">{s.rating.toFixed(1)}</Td><Td><Badge tone={s.grade === 'A' ? 'good' : s.grade === 'B' ? 'info' : 'warning'}>{s.grade}</Badge></Td></tr>)}</tbody>
        </Table>
      </Card>
      <Dialog open={!!dialog} onOpenChange={(o) => !o && setDialog(null)} title={`Add ${dialog}`} footer={<Button onClick={() => create.mutate(undefined)} loading={create.isPending}>Create</Button>}>
        <div className="grid gap-3">
          {dialog === 'warehouse' && <Field label="Code"><Input value={form.code ?? ''} onChange={set('code')} placeholder="WEST" /></Field>}
          <Field label="Name"><Input value={form.name ?? ''} onChange={set('name')} /></Field>
          {dialog === 'warehouse' && <Field label="Location"><Input value={form.location ?? ''} onChange={set('location')} /></Field>}
          {dialog === 'supplier' && <><Field label="Email"><Input value={form.email ?? ''} onChange={set('email')} /></Field><Field label="Lead time (days)"><Input type="number" value={form.lead ?? '7'} onChange={set('lead')} /></Field></>}
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
