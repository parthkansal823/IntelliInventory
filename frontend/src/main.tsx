import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Toaster } from 'sonner'
import { App } from './App'
import { AuthProvider } from './hooks/useAuth'
import { useTheme } from './hooks/useTheme'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 20_000, refetchOnWindowFocus: false, retry: (count, err) => count < 2 && (err as { status?: number }).status !== 401 },
  },
})

function ThemedToaster() {
  const { isDark } = useTheme()
  return <Toaster theme={isDark ? 'dark' : 'light'} position="top-center" richColors closeButton />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <App />
        <ThemedToaster />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
