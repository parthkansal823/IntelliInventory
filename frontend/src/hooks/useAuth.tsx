import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, setUnauthorizedHandler, tokenStore } from '@/lib/api'
import type { Role, User } from '@/lib/types'

const RANK: Record<Role, number> = { viewer: 0, staff: 1, manager: 2, admin: 3 }

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  can: (role: Role) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(() => !!tokenStore.get())
  const qc = useQueryClient()

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
    qc.clear()
  }, [qc])

  useEffect(() => {
    setUnauthorizedHandler(logout)
    if (!tokenStore.get()) return
    api<User>('/api/auth/me')
      .then(setUser)
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false))
  }, [logout])

  const login = useCallback(async (email: string, password: string) => {
    const res = await api<{ access_token: string; user: User }>('/api/auth/token', { method: 'POST', json: { email, password } })
    tokenStore.set(res.access_token)
    setUser(res.user)
  }, [])

  const can = useCallback((role: Role) => !!user && RANK[user.role] >= RANK[role], [user])
  const value = useMemo(() => ({ user, loading, login, logout, can }), [user, loading, login, logout, can])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
