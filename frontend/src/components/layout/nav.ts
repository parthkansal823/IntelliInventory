import { Bot, Boxes, ClipboardList, LayoutDashboard, Lightbulb, Receipt, ScanLine, Settings, ShoppingCart, Workflow } from 'lucide-react'

/** Sidebar, grouped by how often a shop uses each page. `key` = the "g <key>" keyboard shortcut. */
export const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, key: 'd', section: 'Daily' },
  { to: '/billing', label: 'Billing', icon: Receipt, key: 'b', section: 'Daily' },
  { to: '/inventory', label: 'Stock', icon: Boxes, key: 'i', section: 'Daily' },
  { to: '/scan', label: 'Scan', icon: ScanLine, key: 's', section: 'Daily' },
  { to: '/purchase-orders', label: 'Purchase orders', icon: ShoppingCart, key: 'p', section: 'Planning' },
  { to: '/insights', label: 'Insights & festivals', icon: Lightbulb, key: 'n', section: 'Planning' },
  { to: '/counts', label: 'Stock counting', icon: ClipboardList, key: 'o', section: 'Planning' },
  { to: '/copilot', label: 'AI Copilot', icon: Bot, key: 'c', section: 'AI & setup' },
  { to: '/automation', label: 'Automation', icon: Workflow, key: 'a', section: 'AI & setup' },
  { to: '/settings', label: 'Settings', icon: Settings, key: 't', section: 'AI & setup' },
] as const
