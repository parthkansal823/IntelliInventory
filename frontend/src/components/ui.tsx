/** Small shadcn-style UI kit built on Radix primitives + Tailwind v4 tokens. */
import { Check, ChevronDown, Copy, LoaderCircle, X } from 'lucide-react'
import { Dialog as D, Switch as S, Tabs as T, Tooltip as TT } from 'radix-ui'
import {
  forwardRef,
  useState,
  type ButtonHTMLAttributes,
  type ComponentProps,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react'
import { cn } from '@/lib/utils'

// --- Button -------------------------------------------------------------------------

const variants = {
  primary: 'bg-brand text-brand-fg hover:opacity-90 shadow-sm',
  secondary: 'bg-surface border border-border text-fg hover:bg-surface-2 shadow-xs',
  ghost: 'text-muted hover:text-fg hover:bg-surface-2',
  danger: 'bg-critical text-white hover:opacity-90',
  success: 'bg-good text-white hover:opacity-90',
} as const
const sizes = { sm: 'h-8 px-2.5 text-xs gap-1.5', md: 'h-9 px-3.5 text-sm gap-2', lg: 'h-11 px-5 text-sm gap-2', icon: 'h-9 w-9' } as const

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof variants
  size?: keyof typeof sizes
  loading?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', loading, className, children, disabled, ...props }, ref) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-lg font-medium transition-all outline-none',
        'focus-visible:ring-2 focus-visible:ring-brand/50 disabled:pointer-events-none disabled:opacity-50 active:scale-[0.98]',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    >
      {loading && <LoaderCircle className="size-4 animate-spin" />}
      {children}
    </button>
  ),
)
Button.displayName = 'Button'

// --- Card ---------------------------------------------------------------------------------

export function Card({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('rounded-xl border border-border bg-surface shadow-xs', className)} {...props} />
}

export function CardHeader({ title, description, action, icon, className }: { title: ReactNode; description?: ReactNode; action?: ReactNode; icon?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex items-start justify-between gap-3 px-5 pt-4 pb-3', className)}>
      <div className="flex min-w-0 items-start gap-2.5">
        {icon && <div className="mt-0.5 text-muted">{icon}</div>}
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-fg">{title}</h3>
          {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
        </div>
      </div>
      {action}
    </div>
  )
}

// --- Form controls --------------------------------------------------------------------------

const field = 'w-full rounded-lg border border-border bg-surface px-3 text-sm text-fg placeholder:text-subtle outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20 disabled:opacity-60'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => (
  <input ref={ref} className={cn(field, 'h-9', className)} {...props} />
))
Input.displayName = 'Input'

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(field, 'py-2', className)} {...props} />
))
Textarea.displayName = 'Textarea'

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select className={cn(field, 'h-9 appearance-none pr-8', className)} {...props}>
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-subtle" />
    </div>
  )
}

export function Field({ label, hint, children, className }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cn('block space-y-1.5', className)}>
      <span className="text-xs font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="block text-xs text-subtle">{hint}</span>}
    </label>
  )
}

export function Switch({ checked, onCheckedChange, disabled, label }: { checked: boolean; onCheckedChange: (v: boolean) => void; disabled?: boolean; label?: string }) {
  return (
    <S.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={label}
      className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full bg-border transition-colors data-[state=checked]:bg-brand disabled:cursor-not-allowed disabled:opacity-50"
    >
      <S.Thumb className="block size-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
    </S.Root>
  )
}

export function Segmented<V extends string>({ value, onChange, options, size = 'md' }: { value: V; onChange: (v: V) => void; options: { value: V; label: ReactNode }[]; size?: 'sm' | 'md' }) {
  return (
    <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-md font-medium transition',
            size === 'sm' ? 'px-2 py-1 text-xs' : 'px-3 py-1.5 text-sm',
            value === o.value ? 'bg-surface text-fg shadow-xs' : 'text-muted hover:text-fg',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

// --- Tabs ----------------------------------------------------------------------------------

export const Tabs = T.Root
export function TabsList({ className, ...props }: ComponentProps<typeof T.List>) {
  return <T.List className={cn('flex gap-1 overflow-x-auto border-b border-border', className)} {...props} />
}
export function TabsTrigger({ className, ...props }: ComponentProps<typeof T.Trigger>) {
  return (
    <T.Trigger
      className={cn(
        '-mb-px inline-flex items-center gap-1.5 border-b-2 border-transparent px-3 py-2 text-sm font-medium whitespace-nowrap text-muted transition hover:text-fg',
        'data-[state=active]:border-brand data-[state=active]:text-fg',
        className,
      )}
      {...props}
    />
  )
}
export function TabsContent({ className, ...props }: ComponentProps<typeof T.Content>) {
  return <T.Content className={cn('animate-fade-in pt-4 outline-none', className)} {...props} />
}

// --- Dialog & Sheet ----------------------------------------------------------------------------

export function Dialog({ open, onOpenChange, title, description, children, footer, wide }: { open: boolean; onOpenChange: (o: boolean) => void; title: ReactNode; description?: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px] animate-fade-in" />
        <D.Content
          className={cn(
            'fixed top-1/2 left-1/2 z-50 flex max-h-[90vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-2xl border border-border bg-surface shadow-2xl outline-none animate-fade-in',
            wide ? 'max-w-3xl' : 'max-w-lg',
          )}
        >
          <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
            <div>
              <D.Title className="text-base font-semibold">{title}</D.Title>
              {description ? <D.Description className="mt-0.5 text-sm text-muted">{description}</D.Description> : <D.Description className="sr-only">{String(title)}</D.Description>}
            </div>
            <D.Close className="rounded-md p-1 text-muted hover:bg-surface-2 hover:text-fg" aria-label="Close">
              <X className="size-4" />
            </D.Close>
          </div>
          <div className="overflow-y-auto px-5 py-4">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t border-border px-5 py-3">{footer}</div>}
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}

export function Sheet({ open, onOpenChange, title, description, children, headerAction }: { open: boolean; onOpenChange: (o: boolean) => void; title: ReactNode; description?: ReactNode; children: ReactNode; headerAction?: ReactNode }) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/30 animate-fade-in" />
        <D.Content className="fixed inset-y-0 right-0 z-40 flex w-full max-w-2xl flex-col border-l border-border bg-bg shadow-2xl outline-none animate-slide-in">
          <div className="flex items-start justify-between gap-4 border-b border-border bg-surface px-5 py-4">
            <div className="min-w-0">
              <D.Title className="truncate text-base font-semibold">{title}</D.Title>
              {description ? <D.Description className="mt-0.5 text-sm text-muted">{description}</D.Description> : <D.Description className="sr-only">Details</D.Description>}
            </div>
            <div className="flex items-center gap-2">
              {headerAction}
              <D.Close className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-fg" aria-label="Close">
                <X className="size-4" />
              </D.Close>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-5">{children}</div>
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}

export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <TT.Provider delayDuration={250}>
      <TT.Root>
        <TT.Trigger asChild>{children}</TT.Trigger>
        <TT.Portal>
          <TT.Content sideOffset={6} className="z-50 max-w-xs rounded-md bg-fg px-2 py-1 text-xs text-bg shadow-lg animate-fade-in">
            {content}
          </TT.Content>
        </TT.Portal>
      </TT.Root>
    </TT.Provider>
  )
}

// --- Display ---------------------------------------------------------------------------------------

const tones = {
  neutral: 'bg-surface-2 text-muted border-border',
  brand: 'bg-brand-soft text-brand border-brand/20',
  good: 'bg-good/10 text-[#0a7d0a] dark:text-[#4ade80] border-good/25',
  warning: 'bg-warning/15 text-[#8a5a00] dark:text-[#fcd34d] border-warning/30',
  serious: 'bg-serious/15 text-[#a8431c] dark:text-[#fdba74] border-serious/30',
  critical: 'bg-critical/10 text-critical dark:text-[#f87171] border-critical/25',
  info: 'bg-[#2a78d6]/10 text-[#1c5cab] dark:text-[#86b6ef] border-[#2a78d6]/25',
} as const
export type Tone = keyof typeof tones

export function Badge({ tone = 'neutral', className, children, ...props }: ComponentProps<'span'> & { tone?: Tone }) {
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap', tones[tone], className)} {...props}>
      {children}
    </span>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-md bg-surface-2', className)} />
}

export function Spinner({ className }: { className?: string }) {
  return <LoaderCircle className={cn('size-4 animate-spin text-muted', className)} />
}

export function EmptyState({ icon, title, description, action }: { icon?: ReactNode; title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon && <div className="mb-1 rounded-xl bg-surface-2 p-3 text-muted">{icon}</div>}
      <p className="text-sm font-medium">{title}</p>
      {description && <p className="max-w-sm text-sm text-muted">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-muted">{children}</kbd>
}

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)
  return (
    <Button
      variant="secondary"
      size="sm"
      onClick={() => {
        navigator.clipboard?.writeText(text)
        setDone(true)
        window.setTimeout(() => setDone(false), 1500)
      }}
    >
      {done ? <Check className="size-3.5 text-good" /> : <Copy className="size-3.5" />}
      {done ? 'Copied' : label}
    </Button>
  )
}

export function CodeBlock({ code }: { code: string }) {
  return (
    <div className="group relative">
      <pre className="overflow-x-auto rounded-lg border border-border bg-surface-2 p-3 font-mono text-xs leading-relaxed">{code}</pre>
      <div className="absolute top-2 right-2 opacity-0 transition group-hover:opacity-100">
        <CopyButton text={code} />
      </div>
    </div>
  )
}

/** Table primitives */
export function Table({ className, ...props }: ComponentProps<'table'>) {
  return (
    <div className="overflow-x-auto">
      <table className={cn('w-full text-sm', className)} {...props} />
    </div>
  )
}
export function Th({ className, ...props }: ComponentProps<'th'>) {
  return <th className={cn('border-b border-border px-4 py-2.5 text-left text-xs font-medium whitespace-nowrap text-muted', className)} {...props} />
}
export function Td({ className, ...props }: ComponentProps<'td'>) {
  return <td className={cn('border-b border-border/70 px-4 py-2.5 align-middle', className)} {...props} />
}
