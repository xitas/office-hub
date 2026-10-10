import {
  Activity,
  BarChart3,
  Bell,
  Building,
  Building2,
  CalendarDays,
  CheckSquare,
  ClipboardList,
  LayoutDashboard,
  MapPin,
  MessagesSquare,
  Settings,
  SquareKanban,
  ShieldCheck,
  Users,
  UsersRound,
  type LucideIcon,
} from 'lucide-react'

export interface NavItem {
  key: string
  path: string
  icon: LucideIcon
  /** i18n key */
  label: string
  /** "module.action" from the backend permission matrix */
  permission?: string
  /** Hidden until the module's phase ships. Flip to true as each phase lands. */
  enabled: boolean
  /** Shown in the mobile bottom bar (max 4; the rest go under "More"). */
  mobilePrimary?: boolean
  section: 'main' | 'admin'
}

export const NAV_ITEMS: NavItem[] = [
  { key: 'dashboard', path: '/', icon: LayoutDashboard, label: 'nav.dashboard', permission: 'dashboard.view', enabled: true, mobilePrimary: true, section: 'main' },
  { key: 'contacts', path: '/contacts', icon: UsersRound, label: 'nav.contacts', permission: 'contacts.view', enabled: true, mobilePrimary: true, section: 'main' },
  { key: 'pipeline', path: '/pipeline', icon: SquareKanban, label: 'nav.pipeline', permission: 'contacts.view', enabled: true, section: 'main' },
  { key: 'companies', path: '/companies', icon: Building, label: 'nav.companies', permission: 'contacts.view', enabled: true, section: 'main' },
  { key: 'tasks', path: '/tasks', icon: CheckSquare, label: 'nav.tasks', permission: 'tasks.view', enabled: true, mobilePrimary: true, section: 'main' },
  { key: 'chat', path: '/chat', icon: MessagesSquare, label: 'nav.chat', permission: 'chat.view', enabled: false, mobilePrimary: true, section: 'main' },
  { key: 'calendar', path: '/calendar', icon: CalendarDays, label: 'nav.calendar', permission: 'calendar.view', enabled: false, section: 'main' },
  { key: 'visits', path: '/visits', icon: MapPin, label: 'nav.visits', permission: 'visits.view', enabled: false, section: 'main' },
  { key: 'reports', path: '/reports', icon: BarChart3, label: 'nav.reports', permission: 'reports.view', enabled: false, section: 'main' },
  { key: 'team', path: '/team', icon: Users, label: 'nav.team', permission: 'users.view', enabled: true, mobilePrimary: true, section: 'main' },
  { key: 'notifications', path: '/notifications', icon: Bell, label: 'nav.notifications', enabled: true, mobilePrimary: true, section: 'main' },
  { key: 'settings', path: '/settings', icon: Settings, label: 'nav.settings', enabled: true, section: 'main' },
  { key: 'users', path: '/admin/users', icon: Users, label: 'nav.users', permission: 'users.create', enabled: true, section: 'admin' },
  { key: 'departments', path: '/admin/departments', icon: Building2, label: 'nav.departments', permission: 'departments.create', enabled: true, section: 'admin' },
  { key: 'organization', path: '/admin/organization', icon: ShieldCheck, label: 'nav.organization', permission: 'settings.edit', enabled: true, section: 'admin' },
  { key: 'system', path: '/admin/system', icon: Activity, label: 'nav.system', permission: 'settings.edit', enabled: true, section: 'admin' },
  { key: 'audit', path: '/admin/audit-log', icon: ClipboardList, label: 'nav.auditLog', permission: 'audit.view', enabled: true, section: 'admin' },
]

export function visibleNavItems(permissions: string[]) {
  return NAV_ITEMS.filter((item) => item.enabled && (!item.permission || permissions.includes(item.permission)))
}
