export type Role = 'admin' | 'manager' | 'staff' | 'viewer'
export type StockStatus = 'out' | 'critical' | 'low' | 'healthy' | 'overstock'
export type POStatus = 'draft' | 'approved' | 'ordered' | 'received' | 'cancelled'

export interface User {
  id: number
  email: string
  name: string
  role: Role
  is_active: boolean
  created_at: string
}

export interface ProductRow {
  id: number
  sku: string
  name: string
  description: string | null
  category_id: number | null
  supplier_id: number | null
  unit_cost: number
  unit_price: number
  min_order_qty: number
  is_active: boolean
  manual_reorder_point: number | null
  manual_safety_stock: number | null
  lead_time_override: number | null
  category?: string | null
  supplier?: string | null
  on_hand?: number
  on_order?: number
  avg_daily_demand?: number
  demand_std?: number
  lead_time_days?: number
  safety_stock?: number
  reorder_point?: number
  eoq?: number
  days_of_cover?: number | null
  stockout_date?: string | null
  status?: StockStatus
  suggested_order_qty?: number
  stock_value?: number
  abc_class?: 'A' | 'B' | 'C'
}

export interface Movement {
  id: number
  created_at: string
  type: string
  quantity: number
  warehouse: string
  reference: string | null
  note: string | null
  actor: string
  sku?: string
  name?: string
  product_id?: number
}

export interface ForecastData {
  method: string
  mape: number | null
  trend_per_day: number
  total_forecast: number
  avg_daily_forecast: number
  history: { date: string; actual: number }[]
  forecast: { date: string; forecast: number; lower: number; upper: number }[]
}

export interface ProductDetail extends ProductRow {
  warehouses: { warehouse_id: number; code: string; name: string; quantity: number }[]
  movements: Movement[]
  forecast: ForecastData | null
}

export interface Dashboard {
  kpis: {
    total_skus: number
    total_units: number
    inventory_value: number
    low_stock: number
    out_of_stock: number
    overstock: number
    open_purchase_orders: number
    open_alerts: number
    revenue_30d: number
    revenue_change_pct: number | null
    reorder_needed: number
  }
  sales_trend: { date: string; units: number; revenue: number }[]
  category_value: { category: string; value: number }[]
  status_breakdown: { status: StockStatus; count: number }[]
  top_movers: { sku: string; name: string; avg_daily_demand: number; daily_revenue: number; status: StockStatus }[]
}

export interface Alert {
  id: number
  kind: string
  severity: 'critical' | 'warning' | 'info'
  message: string
  resolved: boolean
  product: { id: number; sku: string; name: string } | null
  created_at: string
}

export interface POLine {
  id: number
  product_id: number
  sku: string
  name: string
  quantity: number
  unit_cost: number
  total: number
}

export interface PurchaseOrder {
  id: number
  number: string
  status: POStatus
  supplier: { id: number; name: string } | null
  warehouse: { id: number; code: string; name: string } | null
  created_by: string
  notes: string | null
  created_at: string
  expected_at: string | null
  received_at: string | null
  lines: POLine[]
  total: number
  units: number
}

export interface Recommendation extends Required<Pick<ProductRow, 'sku' | 'name' | 'status' | 'on_hand' | 'on_order' | 'reorder_point' | 'suggested_order_qty' | 'unit_cost'>> {
  product_id: number
  supplier: string | null
  supplier_id: number | null
  days_of_cover: number | null
  estimated_cost: number
  reason: string
  abc_class: string
}

export interface Anomaly {
  kind: 'demand_spike' | 'demand_drop' | 'shrinkage'
  severity: 'critical' | 'warning' | 'info'
  sku: string
  name: string
  date: string
  value: number
  baseline: number
  z_score: number | null
  message: string
}

export interface SupplierScore {
  id: number
  name: string
  email: string | null
  phone: string | null
  rating: number
  promised_lead_time: number
  actual_lead_time: number | null
  on_time_rate: number | null
  orders_received: number
  open_orders: number
  spend: number
  score: number
  grade: 'A' | 'B' | 'C'
  products: number
}

export interface Simulation {
  product: { id: number; sku: string; name: string; on_hand: number; on_order: number }
  policy: { lead_time_days: number; service_level: number; z: number; safety_stock: number; reorder_point: number; order_qty: number; eoq: number; demand_multiplier: number }
  results: {
    fill_rate: number
    stockout_probability: number
    expected_stockout_days: number
    avg_inventory: number
    orders_placed: number
    holding_cost: number
    ordering_cost: number
    lost_sales_value: number
  }
  projection: { day: number; p10: number; p50: number; p90: number; demand: number }[]
  runs: number
  horizon: number
}

export interface CycleCountSummary {
  id: number
  number: string
  status: 'open' | 'posted' | 'cancelled'
  scope: string
  warehouse: { id: number; code: string; name: string }
  created_by: string
  created_at: string
  posted_at: string | null
  lines?: { id: number; product_id: number; sku: string; name: string; expected: number; counted: number | null; variance: number | null; variance_value: number | null }[]
  progress: { counted: number; total: number }
  net_variance_units: number
  net_variance_value: number
  accuracy_pct: number | null
}

export interface Warehouse { id: number; code: string; name: string; location: string | null; units?: number; value?: number }
export interface Category { id: number; name: string; color: string }
export interface Supplier { id: number; name: string; email: string | null; phone: string | null; lead_time_days: number; rating: number }

export interface AgentInfo { name: string; title: string; description: string; color: string; icon: string; tools: string[]; can_delegate: boolean }
export interface ProviderInfo { name: 'hermes' | 'claude' | 'offline'; label: string; configured: boolean; free: boolean; model?: string | null; base_url?: string; setup: string; error?: string }
export interface ToolInfo { name: string; description: string; requires_approval: boolean; mutates: boolean; tags: string[]; parameters: unknown }
export interface HookInfo { name: string; event?: string; pattern?: string; description: string; priority: number; builtin: boolean; enabled: boolean; kind: 'agent' | 'event'; async?: boolean }

export interface AgentsOverview {
  agents: AgentInfo[]
  tools: ToolInfo[]
  providers: ProviderInfo[]
  active_provider: string
  hooks: HookInfo[]
}

export interface Approval {
  id: number
  conversation_id: string | null
  agent: string
  tool: string
  args: Record<string, unknown>
  reason: string | null
  status: 'pending' | 'approved' | 'rejected' | 'failed'
  result: Record<string, unknown> | null
  created_at: string
  decided_at: string | null
}

export interface ConversationSummary { id: string; title: string; agent: string; provider: string; updated_at: string; turns: number }

/** Items rendered in the chat - identical shape to the backend's persisted `display` log. */
export type ChatItem =
  | { type: 'user'; text: string; ts?: string; user?: string | null }
  | { type: 'text' | 'thinking'; agent: string; depth: number; text: string }
  | { type: 'agent_start'; agent: string; depth: number; title: string; provider: string; model: string | null; color: string }
  | { type: 'agent_end'; agent: string; depth: number; text: string }
  | { type: 'tool_call'; agent: string; depth: number; id: string; name: string; args: Record<string, unknown> }
  | { type: 'tool_result'; agent: string; depth: number; id: string; name: string; ok: boolean; duration_ms: number; result: unknown }
  | { type: 'hook'; agent: string; depth: number; tool: string; hook: string; action: string; message: string | null }
  | { type: 'approval'; agent: string; depth: number; approval: Approval }
  | { type: 'approval_resolved'; agent: string; depth: number; approval: Approval }
  | { type: 'error'; agent: string; depth: number; message: string; hint?: string }

export interface TraceSummary {
  id: string
  conversation_id: string | null
  agent: string
  provider: string
  model: string | null
  trigger: string
  input: string
  status: string
  duration_ms: number
  input_tokens: number
  output_tokens: number
  steps: number
  tool_calls: number
  created_at: string
}

export interface TraceStep { kind: 'llm' | 'tool' | 'hook' | 'approval' | 'delegate'; at_ms: number; agent: string; [key: string]: unknown }
export interface TraceDetail extends Omit<TraceSummary, 'steps' | 'tool_calls'> { steps: TraceStep[]; output: string }

export interface LiveEvent { id: string; type: string; payload: Record<string, unknown>; source: string; ts: string }
export interface Report { id: number; kind: string; title: string; content: string; created_by: string; created_at: string }
export interface Webhook { id: number; url: string; events: string[]; active: boolean; has_secret: boolean; last_status: number | null; last_error: string | null; last_delivery_at: string | null; created_at: string; secret?: string }
export interface Job { name: string; description: string; interval_minutes: number; last_run: string | null; next_run: string | null; last_result: string | null }
export interface Plugin { name: string; source: string; registered: string[]; description: string }
