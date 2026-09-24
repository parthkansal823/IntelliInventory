import { Command } from 'cmdk'
import { Bot, Moon, Package, Sparkles, Sun } from 'lucide-react'
import { Dialog as D } from 'radix-ui'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useProducts } from '@/hooks/queries'
import { useTheme } from '@/hooks/useTheme'
import { NAV } from './nav'
import { StatusBadge } from '../domain'

const QUICK_ASKS = [
  'What should I reorder today?',
  'Give me this morning’s briefing',
  'Any anomalies this week?',
  'What’s our inventory health score?',
  'Suggest markdowns for overstock',
]

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()
  const products = useProducts()
  const { setTheme, isDark } = useTheme()

  const go = (to: string) => {
    onOpenChange(false)
    setQuery('')
    navigate(to)
  }
  const ask = (q: string) => go(`/copilot?q=${encodeURIComponent(q)}`)
  const item = 'flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm text-fg data-[selected=true]:bg-surface-2'
  const group = 'px-2 py-1.5 text-xs font-medium text-subtle [&_[cmdk-group-heading]]:px-1 [&_[cmdk-group-heading]]:pb-1.5'

  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px]" />
        <D.Content className="fixed top-[12vh] left-1/2 z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl outline-none animate-fade-in">
          <D.Title className="sr-only">Command palette</D.Title>
          <D.Description className="sr-only">Search products and pages or ask the AI copilot</D.Description>
          <Command label="Command palette" loop>
            <Command.Input
              value={query}
              onValueChange={setQuery}
              placeholder="Type a product, a page, or a question for Copilot…"
              className="h-12 w-full border-b border-border bg-transparent px-4 text-sm outline-none placeholder:text-subtle"
            />
            <Command.List className="max-h-[60vh] overflow-y-auto p-2">
              <Command.Empty className="px-3 py-6 text-center text-sm text-muted">No matches — press Enter to ask Copilot.</Command.Empty>
              {query.trim().length > 2 && (
                <Command.Group heading="Ask AI" className={group}>
                  <Command.Item value={`ask ${query}`} onSelect={() => ask(query)} className={item}>
                    <Sparkles className="size-4 text-brand" />
                    Ask Copilot: <span className="truncate font-medium">“{query}”</span>
                  </Command.Item>
                </Command.Group>
              )}
              <Command.Group heading="Pages" className={group}>
                {NAV.map((n) => (
                  <Command.Item key={n.to} value={`page ${n.label}`} onSelect={() => go(n.to)} className={item}>
                    <n.icon className="size-4 text-muted" />
                    {n.label}
                    <span className="ml-auto font-mono text-[10px] text-subtle">g {n.key}</span>
                  </Command.Item>
                ))}
              </Command.Group>
              <Command.Group heading="Products" className={group}>
                {(products.data ?? []).map((p) => (
                  <Command.Item key={p.id} value={`${p.sku} ${p.name} ${p.category ?? ''}`} onSelect={() => go(`/inventory?product=${p.id}`)} className={item}>
                    <Package className="size-4 text-muted" />
                    <span className="font-mono text-xs text-muted">{p.sku}</span>
                    <span className="truncate">{p.name}</span>
                    <span className="ml-auto">
                      <StatusBadge status={p.status} />
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
              <Command.Group heading="Quick questions" className={group}>
                {QUICK_ASKS.map((q) => (
                  <Command.Item key={q} value={`question ${q}`} onSelect={() => ask(q)} className={item}>
                    <Bot className="size-4 text-muted" />
                    {q}
                  </Command.Item>
                ))}
              </Command.Group>
              <Command.Group heading="Preferences" className={group}>
                <Command.Item value="toggle theme dark light" onSelect={() => { setTheme(isDark ? 'light' : 'dark'); onOpenChange(false) }} className={item}>
                  {isDark ? <Sun className="size-4 text-muted" /> : <Moon className="size-4 text-muted" />}
                  Switch to {isDark ? 'light' : 'dark'} theme
                </Command.Item>
              </Command.Group>
            </Command.List>
          </Command>
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}
