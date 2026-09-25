/** First-login tutorial (English / हिंदी) + language switch + tutorial video. Re-open any time from the "?" button. */
import { BookUser, CalendarHeart, Languages, PlayCircle, ReceiptIndianRupee, ScanBarcode, TriangleAlert, Wallet } from 'lucide-react'
import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { useBillingProfile } from '@/hooks/queries'
import { useAuth } from '@/hooks/useAuth'
import { setLang, useLang, useT } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { Button, Dialog, Tooltip } from './ui'

// --- tiny store so the header "?" button can re-open the tour -------------------------------------
let tourOpen = false
const listeners = new Set<() => void>()
const setTour = (open: boolean) => {
  tourOpen = open
  listeners.forEach((fn) => fn())
}
export const openTutorial = () => setTour(true)
const useTourOpen = () =>
  useSyncExternalStore(
    (fn) => {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
    () => tourOpen,
  )

const seenKey = (userId: number) => `ii-tour-done-${userId}`
function seen(userId: number): boolean {
  try {
    return localStorage.getItem(seenKey(userId)) === '1'
  } catch {
    return true // storage blocked: don't nag on every page load
  }
}
function markSeen(userId: number) {
  try {
    localStorage.setItem(seenKey(userId), '1')
  } catch {
    /* ignore */
  }
}

export function LangToggle({ className }: { className?: string }) {
  const lang = useLang()
  const t = useT()
  return (
    <Tooltip content={t('Language')}>
      <div className={cn('inline-flex rounded-lg border border-border bg-surface-2 p-0.5 text-xs font-semibold', className)} role="group" aria-label={t('Language')}>
        {(['en', 'hi'] as const).map((l) => (
          <button
            key={l}
            onClick={() => setLang(l)}
            className={cn('rounded-md px-2 py-1 transition', lang === l ? 'bg-surface text-fg shadow-xs' : 'text-muted hover:text-fg')}
            aria-pressed={lang === l}
          >
            {l === 'en' ? 'EN' : 'हिं'}
          </button>
        ))}
      </div>
    </Tooltip>
  )
}

const STEPS: { icon: ReactNode; title: string; text: string }[] = [
  { icon: <ReceiptIndianRupee className="size-7" />, title: 'Make a bill', text: 'Billing → type the item name or scan its barcode → choose Cash / UPI / Udhaar → Save bill. Print it or send it on WhatsApp.' },
  { icon: <ScanBarcode className="size-7" />, title: 'Scan barcodes', text: 'Use a USB barcode scanner (just scan — it types the code), or tap Scan to use the phone camera.' },
  { icon: <BookUser className="size-7" />, title: 'Udhaar khata', text: 'Billing → Khata shows who owes you money. Send a WhatsApp reminder or collect with one tap.' },
  { icon: <TriangleAlert className="size-7" />, title: 'Stock & expiry', text: 'The dashboard warns you when stock is low or items are about to expire. Stock shows every item with its barcode and expiry.' },
  { icon: <CalendarHeart className="size-7" />, title: 'Festivals & AI', text: 'Festivals for your state show what to stock and by when. Ask the AI in Hindi: "aaj ki sale?", "kiska udhaar baaki hai?"' },
  { icon: <Wallet className="size-7" />, title: 'Day end: Aaj ka hisaab', text: 'At closing time open Billing → Aaj ka hisaab: total sale, cash in the galla, UPI, udhaar. Print or WhatsApp it.' },
]

export function VideoDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const t = useT()
  return (
    <Dialog open={open} onOpenChange={onOpenChange} wide title={t('Tutorial video')}>
      {/* recorded from the real app - see docs/TUTORIAL.md */}
      <video src="/tutorial.webm" controls autoPlay playsInline className="w-full rounded-lg border border-border bg-black" />
    </Dialog>
  )
}

/** Mounted once in the app layout: opens automatically on a user's first login. */
export function Onboarding() {
  const { user } = useAuth()
  const shop = useBillingProfile().data?.name ?? 'IntelliInventory'
  const open = useTourOpen()
  const lang = useLang()
  const t = useT()
  const [step, setStep] = useState(0)
  const [video, setVideo] = useState(false)

  useEffect(() => {
    if (user && !seen(user.id)) setTour(true)
  }, [user])

  const close = () => {
    if (user) markSeen(user.id)
    setTour(false)
    setStep(0)
  }
  const total = STEPS.length + 1
  const s = step > 0 ? STEPS[step - 1] : null

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(o) => !o && close()}
        title={step === 0 ? t('Welcome to {shop}', { shop }) : t('Step {n} of {total}', { n: step, total: total - 1 })}
        footer={
          <div className="flex w-full items-center justify-between gap-2">
            <Button variant="ghost" onClick={close}>{t('Skip')}</Button>
            <div className="flex gap-2">
              {step > 0 && <Button variant="secondary" onClick={() => setStep(step - 1)}>{t('Back')}</Button>}
              {step < total - 1 ? (
                <Button onClick={() => setStep(step + 1)}>{t('Next')}</Button>
              ) : (
                <Button onClick={close}>{t('Start using the app')}</Button>
              )}
            </div>
          </div>
        }
      >
        {step === 0 ? (
          <div className="space-y-5 text-center">
            <p className="text-sm text-muted">{t("Your shop's billing, stock, udhaar and AI helper — in one simple app.")}</p>
            <div>
              <div className="mb-2 flex items-center justify-center gap-2 text-sm font-medium"><Languages className="size-4" /> {t('Choose your language')}</div>
              <div className="grid grid-cols-2 gap-3">
                {(['en', 'hi'] as const).map((l) => (
                  <button
                    key={l}
                    onClick={() => setLang(l)}
                    className={cn('rounded-xl border-2 p-4 text-lg font-semibold transition', lang === l ? 'border-brand bg-brand-soft text-brand' : 'border-border hover:border-brand/40')}
                  >
                    {l === 'en' ? 'English' : 'हिंदी'}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-xs text-subtle">{t('You can change it any time from the top bar.')}</p>
            </div>
            <Button variant="secondary" onClick={() => setVideo(true)}><PlayCircle className="size-4" /> {t('Watch video')}</Button>
          </div>
        ) : (
          s && (
            <div className="space-y-4 py-2 text-center">
              <div className="mx-auto grid size-16 place-items-center rounded-2xl bg-brand-soft text-brand">{s.icon}</div>
              <h3 className="text-lg font-semibold">{t(s.title)}</h3>
              <p className="text-sm leading-relaxed text-muted">{t(s.text)}</p>
            </div>
          )
        )}
        <div className="mt-4 flex justify-center gap-1.5">
          {Array.from({ length: total }, (_, i) => (
            <button key={i} onClick={() => setStep(i)} aria-label={`${i + 1}`} className={cn('h-1.5 rounded-full transition-all', i === step ? 'w-6 bg-brand' : 'w-1.5 bg-border')} />
          ))}
        </div>
      </Dialog>
      <VideoDialog open={video} onOpenChange={setVideo} />
    </>
  )
}
