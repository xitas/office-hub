import type { AnnouncementsWidget } from './announcements'
import type { TimelineItem } from './timeline'

export type Role = 'admin' | 'manager' | 'staff'
export type TimeFormat = '12h' | '24h'
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
  /** '' = the organization's clock. */
  time_format: TimeFormat | ''
  /** When "due soon" task reminders go out. */
  task_reminder_lead?: '1h' | '1d' | 'off'
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
  /** Clock for everyone who hasn't chosen their own. */
  time_format: TimeFormat
  default_language: Language
  staff_can_import_contacts: boolean
  staff_can_export_contacts: boolean
  /** Office hours ("HH:MM:SS", office time zone): bookings must fit inside. */
  office_opens: string
  office_closes: string
  booking_max_minutes: number
  booking_horizon_days: number
  /** Working week, 0 = Monday … 6 = Sunday: leave counts only these days. */
  working_days: number[]
  /** Minutes after opening before a check-in counts as late. */
  late_after_minutes: number
  /** Remind people who forgot to check in or out. */
  attendance_reminders: boolean
  /** A staff member's own field visit waits for a department manager's approval. */
  visits_need_approval: boolean
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
  tasks_today: DashboardTask[] | null
  overdue: DashboardTask[] | null
  upcoming_deadlines: DashboardTask[] | null
  unread_messages: DashboardListItem[] | null
  pending_approvals: DashboardListItem[] | null
  meetings_today: DashboardListItem[] | null
  bookings_today: DashboardListItem[] | null
  unread_notifications: number | null
  activity: ActivityItem[] | null
  stats: { active_users: number; departments: number | null; logged_in_today: number } | null
  contacts_by_status: {
    scope: 'mine' | 'department' | 'all'
    total: number
    counts: { status: ContactStatus; count: number }[]
  } | null
  /** Latest notes, calls, meetings and status changes (same shape as timeline items). */
  client_activity: TimelineItem[] | null
  /** Managers and admins only. */
  team_workload: WorkloadRow[] | null
  task_completion: TaskCompletion | null
  /** Mentions of me not read yet (Phase 3). */
  chat_mentions: { unread: number } | null
  /** My client follow-ups due within a week, overdue first (Phase 3). */
  follow_ups_due: FollowUpDue[] | null
  /** Current announcements I haven't opened (Phase 3). */
  announcements: AnnouncementsWidget | null
}

export interface DashboardListItem {
  id: number | string
  title: string
  subtitle?: string
  time?: string | null
  /** With `time`: shown as a range (bookings). */
  end?: string | null
  url?: string
  badge?: string | null
}

/** My tasks on the dashboard (tasks_today, overdue, upcoming_deadlines). */
export interface DashboardTask extends DashboardListItem {
  id: number
  due_date: string | null
  due_time: string | null
  priority: 'low' | 'medium' | 'high' | 'urgent'
  status: 'todo' | 'in_progress' | 'review' | 'done'
  is_overdue: boolean
}

export interface WorkloadRow {
  user_id: number
  name: string
  avatar: string | null
  open: number
  overdue: number
}

export interface TaskCompletion {
  week_start: string
  done: number
  created: number
  days: { date: string; done: number; created: number }[]
}

export interface SearchHit {
  id: number | string
  title: string
  subtitle: string
  url: string
  /** Contacts only. */
  status?: ContactStatus
  company?: string | null
  /** Tasks only. */
  task_status?: 'todo' | 'in_progress' | 'review' | 'done'
  due_date?: string | null
  is_overdue?: boolean
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
  /** Where it is, for the map (optional). */
  latitude: string | null
  longitude: string | null
  notes: string
  assigned_to: number | null
  assigned_to_name: string | null
  created_by_name: string | null
  updated_by_name: string | null
  created_at: string
  updated_at: string
  /** Latest call, meeting, email or WhatsApp on the company or its contacts. */
  last_contacted_at?: string | null
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
  /** Where they are, for the map (optional). */
  latitude: string | null
  longitude: string | null
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
  /** Latest call, meeting, email or WhatsApp logged on the contact. */
  last_contacted_at?: string | null
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

/** A client follow-up from a logged call, email, message or note. */
export interface FollowUpDue {
  id: number
  kind: string
  title: string
  summary: string
  due_date: string
  is_overdue: boolean
  url: string
  task_id: number | null
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
  /** Open tasks linked to this contact (that you can see) and the nearest due date. */
  open_tasks?: number
  next_due?: string | null
  last_contacted_at?: string | null
  created_at?: string
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
