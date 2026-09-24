import { useCallback, useEffect, useRef, useState } from 'react'

type Controls = { stop: () => void }

/** Camera barcode / QR scanning with ZXing (lazy-loaded so it never bloats the main bundle). */
export function useBarcodeScanner(onScan: (code: string) => void) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const controls = useRef<Controls | null>(null)
  const lastScan = useRef<{ code: string; at: number }>({ code: '', at: 0 })
  const [active, setActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const callback = useRef(onScan)
  useEffect(() => {
    callback.current = onScan
  }, [onScan])

  const stop = useCallback(() => {
    controls.current?.stop()
    controls.current = null
    setActive(false)
  }, [])

  const start = useCallback(async () => {
    setError(null)
    if (!videoRef.current) return
    try {
      const { BrowserMultiFormatReader } = await import('@zxing/browser')
      const reader = new BrowserMultiFormatReader()
      controls.current = await reader.decodeFromVideoDevice(undefined, videoRef.current, (result) => {
        if (!result) return
        const code = result.getText()
        const now = Date.now()
        // Debounce: the same code is only reported once every 2.5s.
        if (code === lastScan.current.code && now - lastScan.current.at < 2500) return
        lastScan.current = { code, at: now }
        navigator.vibrate?.(60)
        callback.current(code)
      })
      setActive(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Camera unavailable')
      setActive(false)
    }
  }, [])

  useEffect(() => stop, [stop])
  return { videoRef, active, error, start, stop }
}
