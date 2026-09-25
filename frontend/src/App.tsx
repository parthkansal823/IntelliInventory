import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router'
import { AppLayout } from './components/layout/AppLayout'
import { Spinner } from './components/ui'
import { useAuth } from './hooks/useAuth'
import { LiveEventsProvider } from './hooks/useLiveEvents'
import { LoginPage } from './pages/Login'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const Inventory = lazy(() => import('./pages/Inventory'))
const Billing = lazy(() => import('./pages/Billing'))
const Copilot = lazy(() => import('./pages/Copilot'))
const PurchaseOrders = lazy(() => import('./pages/PurchaseOrders'))
const Insights = lazy(() => import('./pages/Insights'))
const Scan = lazy(() => import('./pages/Scan'))
const Counts = lazy(() => import('./pages/Counts'))
const Automation = lazy(() => import('./pages/Automation'))
const SettingsPage = lazy(() => import('./pages/Settings'))

function PageFallback() {
  return (
    <div className="grid h-64 place-items-center">
      <Spinner className="size-6" />
    </div>
  )
}

function Protected({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <PageFallback />
  if (!user) return <Navigate to="/login" replace />
  return <LiveEventsProvider>{children}</LiveEventsProvider>
}

const page = (el: ReactNode) => <Suspense fallback={<PageFallback />}>{el}</Suspense>

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: (
      <Protected>
        <AppLayout />
      </Protected>
    ),
    children: [
      { index: true, element: page(<Dashboard />) },
      { path: 'billing', element: page(<Billing />) },
      { path: 'inventory', element: page(<Inventory />) },
      { path: 'copilot', element: page(<Copilot />) },
      { path: 'purchase-orders', element: page(<PurchaseOrders />) },
      { path: 'insights', element: page(<Insights />) },
      { path: 'scan', element: page(<Scan />) },
      { path: 'counts', element: page(<Counts />) },
      { path: 'automation', element: page(<Automation />) },
      { path: 'settings', element: page(<SettingsPage />) },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
])

export function App() {
  return <RouterProvider router={router} />
}
