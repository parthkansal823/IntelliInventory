/** Header badge for bills saved on this device while offline; syncs them by itself when the server is back. */
import { useQueryClient } from '@tanstack/react-query'
import { CloudUpload, RefreshCw, Trash2, WifiOff } from 'lucide-react'
import { useEffect, useState, useSyncExternalStore } from 'react'
import { toast } from 'sonner'
import { removeBill, retryBill, syncQueue, useOfflineQueue } from '@/lib/offline'
import { tr, useT } from '@/lib/i18n'
import { money, dateTime } from '@/lib/utils'
import { Button, Dialog } from './ui'

const subscribeOnline = (fn: () => void) => {
  window.addEventListener('online', fn)
  window.addEventListener('offline', fn)
  return () => {
    window.removeEventListener('online', fn)
    window.removeEventListener('offline', fn)
  }
}

export function OfflineBadge() {
  const t = useT()
  const queue = useOfflineQueue()
  const online = useSyncExternalStore(subscribeOnline, () => navigator.onLine)
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  const sync = async (manual = false) => {
    setBusy(true)
    try {
      const saved = await syncQueue()
      if (saved) {
        toast.success(tr('{n} offline bill(s) synced', { n: saved }))
        void qc.invalidateQueries()
      } else if (manual) toast.info(tr('Still offline — will try again automatically'))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    const run = () => {
      if (queue.some((b) => !b.error)) void sync()
    }
    run()
    window.addEventListener('online', run)
    const timer = window.setInterval(run, 30_000)
    return () => {
      window.removeEventListener('online', run)
      window.clearInterval(timer)
    }
  }, [queue.length])

  if (online && !queue.length) return null
  const failed = queue.filter((b) => b.error).length
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium ${failed ? 'bg-critical/10 text-critical' : 'bg-warning/10 text-warning'}`}
      >
        {online ? <CloudUpload className="size-3.5" /> : <WifiOff className="size-3.5" />}
        {queue.length ? t('{n} bill(s) to sync', { n: queue.length }) : t('Offline')}
      </button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title={t('Bills saved on this device')}
        description={online ? t('They are sent to the server automatically.') : t('No internet. Billing still works — bills sync when the internet is back.')}
        footer={<Button onClick={() => sync(true)} loading={busy} disabled={!queue.length}><RefreshCw className="size-4" /> {t('Sync now')}</Button>}
      >
        {!queue.length ? <p className="text-sm text-muted">{t('Nothing waiting.')}</p> : (
          <div className="divide-y divide-border">
            {queue.map((b) => (
              <div key={b.client_ref} className="flex items-center justify-between gap-2 py-2 text-sm">
                <div className="min-w-0">
                  <div className="font-medium"><span className="font-mono text-xs">{b.number}</span> · {b.customer} · {money(b.total)}</div>
                  <div className="text-xs text-subtle">{dateTime(b.created_at)}</div>
                  {b.error && <div className="text-xs font-medium text-critical">{b.error}</div>}
                </div>
                <div className="flex shrink-0 gap-1">
                  {b.error && <Button size="sm" variant="secondary" onClick={() => { retryBill(b.client_ref); void sync(true) }}>{t('Retry')}</Button>}
                  <Button size="icon" variant="ghost" className="size-8" aria-label={t('Delete')} onClick={() => { if (window.confirm(t('Delete this offline bill? It will not be saved.'))) removeBill(b.client_ref) }}><Trash2 className="size-4" /></Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Dialog>
    </>
  )
}
