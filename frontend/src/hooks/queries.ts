/** Data hooks - one per resource, all backed by TanStack Query. */
import { useMutation, useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { toast } from 'sonner'
import { get } from '@/lib/api'
import type {
  AgentsOverview,
  Alert,
  Anomaly,
  Approval,
  Category,
  ConversationSummary,
  CycleCountSummary,
  Dashboard,
  FestivalInfo,
  FestivalPlan,
  ForecastData,
  GstReport,
  GstSettings,
  HookInfo,
  Job,
  Plugin,
  ProductDetail,
  ProductRow,
  PurchaseOrder,
  Recommendation,
  Report,
  Supplier,
  SupplierScore,
  TraceDetail,
  TraceSummary,
  User,
  Warehouse,
  Webhook,
} from '@/lib/types'

export const keys = {
  dashboard: ['dashboard'],
  products: ['products'],
  product: (id: number) => ['products', id],
  alerts: ['alerts'],
  pos: (status?: string) => ['purchase-orders', status ?? 'all'],
  poStats: ['purchase-orders', 'stats'],
  reorder: ['reorder'],
  forecast: (id: number) => ['forecast', id],
  abc: ['abc'],
  anomalies: ['anomalies'],
  suppliersScores: ['suppliers', 'scores'],
  margins: ['margins'],
  counts: ['counts'],
  count: (id: number) => ['counts', id],
  warehouses: ['warehouses'],
  categories: ['categories'],
  suppliers: ['suppliers'],
  users: ['users'],
  agents: ['agents'],
  conversations: ['conversations'],
  approvals: (status = 'pending') => ['approvals', status],
  traces: (conversationId?: string) => ['traces', conversationId ?? 'all'],
  trace: (id: string) => ['trace', id],
  reports: ['reports'],
  hooks: ['hooks'],
  webhooks: ['webhooks'],
  jobs: ['jobs'],
  events: ['events'],
  automation: ['automation-settings'],
  system: ['system'],
} as const

export const useDashboard = () => useQuery({ queryKey: keys.dashboard, queryFn: () => get<Dashboard>('/api/analytics/dashboard') })
export const useProducts = () => useQuery({ queryKey: keys.products, queryFn: () => get<ProductRow[]>('/api/products') })
export const useProduct = (id: number | null) =>
  useQuery({ queryKey: keys.product(id ?? 0), queryFn: () => get<ProductDetail>(`/api/products/${id}`), enabled: !!id })
export const useAlerts = () => useQuery({ queryKey: keys.alerts, queryFn: () => get<Alert[]>('/api/alerts') })
export const usePurchaseOrders = (status?: string) =>
  useQuery({ queryKey: keys.pos(status), queryFn: () => get<PurchaseOrder[]>(`/api/purchase-orders${status && status !== 'all' ? `?status=${status}` : ''}`) })
export const usePOStats = () => useQuery({ queryKey: keys.poStats, queryFn: () => get<Record<string, number>>('/api/purchase-orders/stats') })
export const useReorder = () => useQuery({ queryKey: keys.reorder, queryFn: () => get<Recommendation[]>('/api/analytics/reorder') })
export const useForecast = (id: number | null) =>
  useQuery({ queryKey: keys.forecast(id ?? 0), queryFn: () => get<ForecastData>(`/api/analytics/forecast/${id}`), enabled: !!id })
export const useAbc = () =>
  useQuery({
    queryKey: keys.abc,
    queryFn: () => get<{ classes: { class: string; count: number; consumption_value: number; stock_value: number }[]; products: { sku: string; name: string; class: string; monthly_consumption_value: number }[] }>('/api/analytics/abc'),
  })
export const useAnomalies = () => useQuery({ queryKey: keys.anomalies, queryFn: () => get<Anomaly[]>('/api/analytics/anomalies') })
export const useSupplierScores = () => useQuery({ queryKey: keys.suppliersScores, queryFn: () => get<SupplierScore[]>('/api/analytics/suppliers') })
export const useMargins = () =>
  useQuery({
    queryKey: keys.margins,
    queryFn: () => get<{ category: string; color: string; revenue: number; cogs: number; gross_profit: number; margin_pct: number; units: number }[]>('/api/analytics/margins'),
  })
export const useCounts = () => useQuery({ queryKey: keys.counts, queryFn: () => get<CycleCountSummary[]>('/api/counts') })
export const useCount = (id: number | null) =>
  useQuery({ queryKey: keys.count(id ?? 0), queryFn: () => get<CycleCountSummary>(`/api/counts/${id}`), enabled: !!id })
export const useWarehouses = () => useQuery({ queryKey: keys.warehouses, queryFn: () => get<Warehouse[]>('/api/warehouses'), staleTime: 60_000 })
export const useCategories = () => useQuery({ queryKey: keys.categories, queryFn: () => get<Category[]>('/api/categories'), staleTime: 60_000 })
export const useSuppliers = () => useQuery({ queryKey: keys.suppliers, queryFn: () => get<Supplier[]>('/api/suppliers'), staleTime: 60_000 })
export const useUsers = () => useQuery({ queryKey: keys.users, queryFn: () => get<User[]>('/api/users') })
export const useAgents = () => useQuery({ queryKey: keys.agents, queryFn: () => get<AgentsOverview>('/api/agents'), staleTime: 30_000 })
export const useConversations = () => useQuery({ queryKey: keys.conversations, queryFn: () => get<ConversationSummary[]>('/api/agents/conversations') })
export const useApprovals = (status = 'pending') =>
  useQuery({ queryKey: keys.approvals(status), queryFn: () => get<Approval[]>(`/api/agents/approvals?status=${status}`) })
export const useTraces = (conversationId?: string) =>
  useQuery({
    queryKey: keys.traces(conversationId),
    queryFn: () => get<TraceSummary[]>(`/api/agents/traces${conversationId ? `?conversation_id=${conversationId}` : ''}`),
  })
export const useTrace = (id: string | null) =>
  useQuery({ queryKey: keys.trace(id ?? ''), queryFn: () => get<TraceDetail>(`/api/agents/traces/${id}`), enabled: !!id })
export const useReports = () => useQuery({ queryKey: keys.reports, queryFn: () => get<Report[]>('/api/reports?kind=briefing&limit=5') })
export const useHooks = () => useQuery({ queryKey: keys.hooks, queryFn: () => get<{ agent: HookInfo[]; event: HookInfo[]; plugins: Plugin[] }>('/api/hooks') })
export const useWebhooks = () => useQuery({ queryKey: keys.webhooks, queryFn: () => get<Webhook[]>('/api/webhooks') })
export const useJobs = () => useQuery({ queryKey: keys.jobs, queryFn: () => get<Job[]>('/api/jobs') })
export const useAutomationSettings = () =>
  useQuery({ queryKey: keys.automation, queryFn: () => get<{ autopilot_enabled: boolean; autopilot_cooldown_hours: number }>('/api/automation/settings') })
export const useSystemInfo = () =>
  useQuery({
    queryKey: keys.system,
    queryFn: () => get<{ version: string; active_provider: string; mcp: { http_url: string; stdio_command: string; auth_header: string }; database: string }>('/api/system/info'),
  })

/** Mutation helper: runs `fn`, toasts success/error, invalidates the given query keys. */
export function useAction<TArgs, TResult = unknown>(
  fn: (args: TArgs) => Promise<TResult>,
  opts: { success?: string | ((r: TResult) => string); invalidate?: QueryKey[]; onSuccess?: (r: TResult) => void } = {},
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (result) => {
      if (opts.success) toast.success(typeof opts.success === 'function' ? opts.success(result) : opts.success)
      opts.invalidate?.forEach((key) => qc.invalidateQueries({ queryKey: key }))
      opts.onSuccess?.(result)
    },
    onError: (err: Error) => toast.error(err.message),
  })
}

export interface HealthScore {
  score: number
  grade: string
  focus: string
  components: { key: string; label: string; weight: number; score: number; detail: string }[]
}
export interface MarkdownSuggestion {
  product_id: number
  sku: string
  name: string
  category: string | null
  on_hand: number
  days_of_cover: number
  excess_units: number
  capital_tied: number
  suggested_discount_pct: number
  new_price: number
  current_price: number
  projected_days_to_clear: number | null
  margin_after_pct: number
  capped_by_cost: boolean
  action: string
}
export const useHealth = () => useQuery({ queryKey: ['health'], queryFn: () => get<HealthScore>('/api/analytics/health') })
export const useMarkdowns = () => useQuery({ queryKey: ['markdowns'], queryFn: () => get<MarkdownSuggestion[]>('/api/analytics/markdowns') })

export const useFestivals = () => useQuery({ queryKey: ['festivals'], queryFn: () => get<FestivalInfo[]>('/api/india/festivals'), staleTime: 3_600_000 })
export const useFestivalPlan = (festival: string | null) =>
  useQuery({ queryKey: ['festival-plan', festival], queryFn: () => get<FestivalPlan>(`/api/india/festival-plan${festival ? `?festival=${festival}` : ''}`) })
export const useGst = (days = 30) => useQuery({ queryKey: ['gst', days], queryFn: () => get<GstReport>(`/api/india/gst?days=${days}`) })
export const useGstSettings = () => useQuery({ queryKey: ['gst-settings'], queryFn: () => get<GstSettings>('/api/india/settings'), staleTime: 60_000 })
