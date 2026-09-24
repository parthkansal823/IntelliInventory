const TOKEN_KEY = 'ii-token'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

let onUnauthorized: (() => void) | null = null
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn
}

function detail(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const d = (body as { detail: unknown }).detail
    if (typeof d === 'string') return d
    if (Array.isArray(d)) return d.map((e) => (e as { msg?: string }).msg ?? JSON.stringify(e)).join('; ')
  }
  return fallback
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = tokenStore.get()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let body = init.body
  if (init.json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(init.json)
  }
  const res = await fetch(path, { ...init, headers, body })
  if (res.status === 401 && token) onUnauthorized?.()
  const text = await res.text()
  const data = text ? (() => { try { return JSON.parse(text) } catch { return text } })() : null
  if (!res.ok) throw new ApiError(res.status, detail(data, res.statusText || 'Request failed'))
  return data as T
}

export const get = <T,>(path: string) => api<T>(path)
export const post = <T,>(path: string, json?: unknown) => api<T>(path, { method: 'POST', json: json ?? {} })
export const patch = <T,>(path: string, json: unknown) => api<T>(path, { method: 'PATCH', json })
export const put = <T,>(path: string, json: unknown) => api<T>(path, { method: 'PUT', json })
export const del = <T,>(path: string) => api<T>(path, { method: 'DELETE' })

export async function download(path: string, filename: string) {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${tokenStore.get() ?? ''}` } })
  if (!res.ok) throw new ApiError(res.status, 'Download failed')
  const url = URL.createObjectURL(await res.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  a.click()
  URL.revokeObjectURL(url)
}

/** Parse a Server-Sent Events stream from a fetch() response body. */
export async function* readSSE(res: Response): AsyncGenerator<unknown> {
  if (!res.body) return
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let sep: number
    while ((sep = buffer.search(/\r?\n\r?\n/)) !== -1) {
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep).replace(/^\r?\n\r?\n/, '')
      const data = block
        .split(/\r?\n/)
        .filter((l) => l.startsWith('data:'))
        .map((l) => l.slice(5).trimStart())
        .join('\n')
      if (data) {
        try {
          yield JSON.parse(data)
        } catch {
          /* ignore keep-alive / non-JSON frames */
        }
      }
    }
  }
}
