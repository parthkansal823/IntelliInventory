import { Bot, ChartLine, ShieldCheck, Workflow } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router'
import { Button, Card, Field, Input } from '@/components/ui'
import { useAuth } from '@/hooks/useAuth'

const DEMO = [
  { email: 'manager@intelliinventory.dev', role: 'Manager', note: 'approves POs & agent actions' },
  { email: 'admin@intelliinventory.dev', role: 'Admin', note: 'users, webhooks, everything' },
  { email: 'staff@intelliinventory.dev', role: 'Staff', note: 'scans, counts, drafts' },
  { email: 'viewer@intelliinventory.dev', role: 'Viewer', note: 'read-only' },
]

const FEATURES = [
  { icon: Bot, title: 'Multi-agent copilot', text: 'Hermes, Claude or a free offline planner — with human approvals.' },
  { icon: ChartLine, title: 'Forecast & simulate', text: 'Holt-Winters forecasts, Monte-Carlo what-ifs, smart reorder points.' },
  { icon: Workflow, title: 'Hooks everywhere', text: 'Lifecycle hooks, webhooks, autopilot, plugins and MCP.' },
  { icon: ShieldCheck, title: '100% free to run', text: 'SQLite + open-source stack. No paid API required.' },
]

export function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState(DEMO[0].email)
  const [password, setPassword] = useState('demo1234')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
      navigate('/')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-full lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-[#0f0e1a] p-10 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -top-32 -right-32 size-96 rounded-full bg-indigo-500/30 blur-3xl" />
        <div className="absolute -bottom-40 -left-20 size-96 rounded-full bg-violet-600/20 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <img src="/favicon.svg" className="size-10 rounded-xl" alt="" />
          <span className="text-lg font-semibold">IntelliInventory</span>
        </div>
        <div className="relative max-w-md">
          <h1 className="text-3xl leading-tight font-semibold tracking-tight">Inventory that plans itself — and asks before it acts.</h1>
          <div className="mt-8 grid gap-5">
            {FEATURES.map((f) => (
              <div key={f.title} className="flex gap-3">
                <div className="rounded-lg bg-white/10 p-2">
                  <f.icon className="size-4" />
                </div>
                <div>
                  <div className="text-sm font-medium">{f.title}</div>
                  <div className="text-sm text-white/60">{f.text}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
        <p className="relative text-xs text-white/40">FastAPI · React 19 · Hermes Agent · MCP</p>
      </div>

      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <img src="/favicon.svg" className="mb-3 size-10 rounded-xl" alt="" />
            <h1 className="text-xl font-semibold">IntelliInventory</h1>
          </div>
          <h2 className="text-lg font-semibold">Sign in</h2>
          <p className="mt-1 text-sm text-muted">Use a demo account below — the password is prefilled.</p>
          <form onSubmit={submit} className="mt-6 space-y-4">
            <Field label="Email">
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required />
            </Field>
            <Field label="Password">
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            </Field>
            {error && <p className="text-sm text-critical">{error}</p>}
            <Button type="submit" className="w-full" size="lg" loading={busy}>
              Sign in
            </Button>
          </form>
          <Card className="mt-6 divide-y divide-border">
            {DEMO.map((d) => (
              <button
                key={d.email}
                type="button"
                onClick={() => {
                  setEmail(d.email)
                  setPassword('demo1234')
                }}
                className="flex w-full items-center justify-between px-4 py-2.5 text-left text-sm transition first:rounded-t-xl last:rounded-b-xl hover:bg-surface-2"
              >
                <span>
                  <span className="font-medium">{d.role}</span>
                  <span className="ml-2 text-xs text-muted">{d.note}</span>
                </span>
                {email === d.email && <span className="size-2 rounded-full bg-brand" />}
              </button>
            ))}
          </Card>
        </div>
      </div>
    </div>
  )
}
