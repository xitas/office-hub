export type Role = 'admin' | 'manager' | 'staff'
export type Language = 'en' | 'ur'
export type ThemePref = 'light' | 'dark' | 'system'

export interface Me {
  id: number
  email: string
  full_name: string
  phone: string
  job_title: string
  role: Role
  department: number | null
  department_name: string | null
  avatar: string | null
  language: Language
  theme: ThemePref
  two_factor_enabled: boolean
  permissions: string[]
  date_joined: string
  last_login: string | null
}

export interface User {
  id: number
  email: string
  full_name: string
  phone: string
  job_title: string
  role: Role
  department: number | null
  department_name: string | null
  avatar: string | null
  is_active: boolean
  two_factor_enabled: boolean
  last_login: string | null
  date_joined: string
}

export interface Department {
  id: number
  name: string
  description: string
  manager: number | null
  manager_name: string | null
  member_count: number
  created_at: string
}

export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface OrgSettings {
  org_name: string
  currency: string
  date_format: 'DD/MM/YYYY' | 'MM/DD/YYYY' | 'YYYY-MM-DD' | 'DD MMM YYYY'
  timezone: string
  week_start: number
  default_language: Language
  updated_at: string
}

export interface AppNotification {
  id: number
  type: string
  title: string
  body: string
  link: string
  is_read: boolean
  actor_name: string | null
  created_at: string
}

export interface NotificationPref {
  type: string
  label: string
  in_app: boolean
  email: boolean
}

export interface AuditEntry {
  id: number
  actor: number | null
  actor_name: string | null
  action: string
  action_label: string
  model: string | null
  /** Translated record type name, e.g. "user" / "صارف" */
  model_label: string | null
  object_id: string
  object_repr: string
  changes: Record<string, unknown>
  description: string
  ip: string | null
  timestamp: string
}

export interface ActivityItem {
  id: number
  actor_name: string | null
  action: string
  model: string | null
  model_label: string | null
  object_repr: string
  description: string
  timestamp: string
}

/** Widget value is `null` while its module has not been released yet. */
export interface DashboardData {
  tasks_today: DashboardListItem[] | null
  overdue: DashboardListItem[] | null
  upcoming_deadlines: DashboardListItem[] | null
  unread_messages: DashboardListItem[] | null
  pending_approvals: DashboardListItem[] | null
  meetings_today: DashboardListItem[] | null
  bookings_today: DashboardListItem[] | null
  unread_notifications: number | null
  activity: ActivityItem[] | null
  stats: { active_users: number; departments: number | null; logged_in_today: number } | null
}

export interface DashboardListItem {
  id: number | string
  title: string
  subtitle?: string
  time?: string
  url?: string
  badge?: string
}

export interface SearchHit {
  id: number | string
  title: string
  subtitle: string
  url: string
}

export interface Company {
  id: number
  name: string
  industry: string
  industry_label: string
  phone: string
  email: string
  website: string
  address: string
  city: string
  notes: string
  assigned_to: number | null
  assigned_to_name: string | null
  created_by_name: string | null
  updated_by_name: string | null
  created_at: string
  updated_at: string
}

export type ContactStatus = 'new' | 'contacted' | 'in_discussion' | 'won' | 'lost'

export interface Contact {
  id: number
  first_name: string
  last_name: string
  full_name: string
  company: number | null
  company_name: string | null
  job_title: string
  phone: string
  whatsapp: string
  email: string
  address: string
  city: string
  tags: string[]
  status: ContactStatus
  status_label: string
  /** When the current status was set */
  status_changed_at: string
  assigned_to: number | null
  assigned_to_name: string | null
  created_by_name: string | null
  updated_by_name: string | null
  created_at: string
  updated_at: string
}

/** Another contact sharing a phone/WhatsApp number or email (a warning, never blocking). */
export interface DuplicateMatch {
  id: number | null
  name: string | null
  company_name: string | null
  assigned_to_name: string | null
  matched: ('phone' | 'email')[]
  /** false: exists but assigned outside this user's view, so details are hidden */
  visible: boolean
}

export interface Tag {
  id: number
  name: string
}

export interface PipelineCard {
  id: number
  full_name: string
  company: number | null
  company_name: string | null
  assigned_to: number | null
  assigned_to_name: string | null
  tags: string[]
  status: ContactStatus
  status_changed_at: string
  city: string
}

export interface PipelineColumn {
  status: ContactStatus
  label: string
  count: number
  cards: PipelineCard[]
}

export interface PipelineData {
  columns: PipelineColumn[]
  total: number
}
