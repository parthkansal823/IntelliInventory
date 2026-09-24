import { Bot, Boxes, ClipboardList, LayoutDashboard, Lightbulb, ScanLine, Settings, ShoppingCart, Workflow } from 'lucide-react'

export const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, key: 'd' },
  { to: '/inventory', label: 'Inventory', icon: Boxes, key: 'i' },
  { to: '/copilot', label: 'AI Copilot', icon: Bot, key: 'c' },
  { to: '/purchase-orders', label: 'Purchase orders', icon: ShoppingCart, key: 'p' },
  { to: '/insights', label: 'Insights', icon: Lightbulb, key: 'n' },
  { to: '/scan', label: 'Scan', icon: ScanLine, key: 's' },
  { to: '/counts', label: 'Cycle counts', icon: ClipboardList, key: 'o' },
  { to: '/automation', label: 'Automation', icon: Workflow, key: 'a' },
  { to: '/settings', label: 'Settings', icon: Settings, key: 't' },
] as const
