import {
  Activity,
  BarChart3,
  Bell,
  Building,
  Building2,
  DoorOpen,
  CalendarClock,
  CalendarDays,
  CheckSquare,
  FileText,
  ClipboardList,
  LayoutDashboard,
  Megaphone,
  MapPin,
  Palmtree,
  Package,
  ReceiptText,
  UserCheck,
  MessagesSquare,
  ScrollText,
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
  { key: 'log', path: '/log', icon: ScrollText, label: 'nav.log', permission: 'contacts.view', enabled: true, section: 'main' },
  { key: 'templates', path: '/templates', icon: FileText, label: 'nav.templates', permission: 'templates.view', enabled: true, section: 'main' },
  { key: 'tasks', path: '/tasks', icon: CheckSquare, label: 'nav.tasks', permission: 'tasks.view', enabled: true, mobilePrimary: true, section: 'main' },
  { key: 'announcements', path: '/announcements', icon: Megaphone, label: 'nav.announcements', permission: 'announcements.view', enabled: true, section: 'main' },
  { key: 'chat', path: '/chat', icon: MessagesSquare, label: 'nav.chat', permission: 'chat.view', enabled: true, mobilePrimary: true, section: 'main' },
  { key: 'bookings', path: '/bookings', icon: CalendarClock, label: 'nav.bookings', permission: 'bookings.view', enabled: true, section: 'main' },
  { key: 'resources', path: '/resources', icon: DoorOpen, label: 'nav.resources', permission: 'resources.view', enabled: true, section: 'main' },
  { key: 'attendance', path: '/attendance', icon: UserCheck, label: 'nav.attendance', permission: 'attendance.view', enabled: true, section: 'main' },
  { key: 'leave', path: '/leave', icon: Palmtree, label: 'nav.leave', permission: 'leave.view', enabled: true, section: 'main' },
  { key: 'supplies', path: '/supplies', icon: Package, label: 'nav.supplies', permission: 'inventory.view', enabled: true, section: 'main' },
  { key: 'expenses', path: '/expenses', icon: ReceiptText, label: 'nav.expenses', permission: 'expenses.view', enabled: true, section: 'main' },
  { key: 'calendar', path: '/calendar', icon: CalendarDays, label: 'nav.calendar', permission: 'calendar.view', enabled: true, section: 'main' },
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
