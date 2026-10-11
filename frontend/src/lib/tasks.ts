import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { useMe } from './auth'
import { useUserOptions } from './queries'

export const TASK_STATUSES = ['todo', 'in_progress', 'review', 'done'] as const
export type TaskStatus = (typeof TASK_STATUSES)[number]
export const TASK_PRIORITIES = ['low', 'medium', 'high', 'urgent'] as const
export type TaskPriority = (typeof TASK_PRIORITIES)[number]

/** Quick filters on the Tasks page and the query params they send. */
export const QUICK_FILTERS = {
  mine: { mine: 'true' },
  today: { due: 'today' },
  overdue: { due: 'overdue' },
  all: {},
} as const
export type QuickFilter = keyof typeof QUICK_FILTERS

export const TASK_SORTS = ['default', 'due', '-due', 'priority', '-created'] as const

export interface TaskAssignee {
  id: number
  full_name: string
  avatar: string | null
}

export interface Task {
  id: number
  title: string
  description: string
  assignees: number[]
  assignee_details: TaskAssignee[]
  due_date: string | null
  due_time: string | null
  priority: TaskPriority
  priority_label: string
  status: TaskStatus
  status_label: string
  contact: number | null
  contact_name: string | null
  company: number | null
  company_name: string | null
  completed_at: string | null
  is_overdue: boolean
  can_delete: boolean
  checklist_total: number
  checklist_done: number
  comment_count: number
  /** How the task repeats (null: a one-off task). */
  repeat: TaskRepeat | null
  follow_up_of: number | null
  created_by: number | null
  created_by_name: string | null
  updated_by_name: string | null
  created_at: string
  updated_at: string
}

export type TaskInput = Pick<Task, 'title' | 'description' | 'assignees' | 'due_date' | 'due_time' | 'priority' | 'status' | 'contact' | 'company'>

// Theme tokens only, so badges work in light and dark mode.
export const STATUS_STYLES: Record<TaskStatus, string> = {
  todo: 'border-border bg-muted text-foreground',
  in_progress: 'border-primary/30 bg-primary/10 text-primary',
  review: 'border-warning/40 bg-warning/15 text-foreground',
  done: 'border-success/40 bg-success/15 text-success',
}

export const PRIORITY_STYLES: Record<TaskPriority, string> = {
  low: 'border-border text-muted-foreground',
  medium: 'border-border text-foreground',
  high: 'border-warning/50 bg-warning/10 text-foreground',
  urgent: 'border-destructive/40 bg-destructive/10 text-destructive',
}

/** People this user may put on a task: themselves and their department (admins: everyone). */
export function useTaskAssignees() {
  const me = useMe()
  const { data } = useUserOptions()
  const users = data ?? []
  if (me.role === 'admin') return users
  return users.filter((u) => u.id === me.id || (me.department && u.department === me.department))
}

export function useTask(id: string | undefined) {
  return useQuery({
    queryKey: ['tasks', 'detail', id],
    queryFn: async () => (await api.get<Task>(`/tasks/${id}/`)).data,
    enabled: !!id,
    retry: false,
  })
}

/** "HH:MM:SS" from the API → "HH:MM" for inputs and display. */
export const shortTime = (value: string | null) => (value ? value.slice(0, 5) : '')

export interface TaskBoardColumn {
  status: TaskStatus
  label: string
  /** Cards in the column (for Done: completed within the window). */
  count: number
  /** Every task with this status (for Done: all time). */
  total: number
  cards: Task[]
}

export interface TaskBoardData {
  columns: TaskBoardColumn[]
  done_since: string
  done_window_days: number
}

export interface TaskCalendarData {
  start: string
  end: string
  /** The office's date today (its time zone, not the browser's). */
  today: string
  tasks: Task[]
  undated: Task[]
  undated_count: number
}

export const TASK_LAYOUTS = ['list', 'board', 'calendar'] as const
export type TaskLayout = (typeof TASK_LAYOUTS)[number]
const LAYOUT_KEY = 'crm.tasks.layout'

/** The last Tasks view this browser used (List / Board / Calendar). */
export function loadLayout(): TaskLayout {
  try {
    const saved = localStorage.getItem(LAYOUT_KEY)
    return TASK_LAYOUTS.includes(saved as TaskLayout) ? (saved as TaskLayout) : 'list'
  } catch {
    return 'list'
  }
}

export function saveLayout(layout: TaskLayout) {
  try {
    localStorage.setItem(LAYOUT_KEY, layout)
  } catch {
    // Private mode or storage blocked: the choice just isn't remembered.
  }
}

/** "YYYY-MM-DD" for a moment as seen on the office's clock. */
export function officeDate(timeZone: string, at: Date = new Date()) {
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(at)
  } catch {
    return new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(at)
  }
}

export interface ChecklistItem {
  id: number
  text: string
  done: boolean
  position: number
  done_by_name: string | null
  done_at: string | null
  created_at: string
}

export interface TaskAttachment {
  id: number
  original_name: string
  size: number
  content_type: string
  kind: 'image' | 'pdf' | 'office' | 'text' | 'zip'
  comment: number | null
  uploaded_by_name: string | null
  created_at: string
  /** API paths (fetched with the user's token). */
  download_url: string
  thumbnail_url: string | null
  can_delete: boolean
}

export interface TaskComment {
  id: number
  body: string
  author: number | null
  author_name: string | null
  author_avatar: string | null
  created_at: string
  edited_at: string | null
  attachments: TaskAttachment[]
  can_edit: boolean
  can_delete: boolean
}

export type TaskActivityItem =
  | { type: 'event'; id: string; kind: string; data: Record<string, unknown>; actor_name: string | null; created_at: string }
  | { type: 'comment'; id: string; created_at: string; comment: TaskComment }

export interface TaskActivityData {
  items: TaskActivityItem[]
  /** Files on the task itself (comment files are listed with their comment). */
  attachments: TaskAttachment[]
}

export interface MentionPerson {
  id: number
  full_name: string
  avatar: string | null
}

/** Allowed uploads (the server checks the real content too). */
export const ATTACHMENT_ACCEPT = '.pdf,.png,.jpg,.jpeg,.gif,.webp,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.zip'
export const ATTACHMENT_MAX_MB = 10

/** @[Full Name](user:12) tokens written by the mention picker. */
export const MENTION_RE = /@\[([^\]\n]{1,150})\]\(user:(\d+)\)/g

/** Stored body → editable text ("@Full Name") plus the people it mentions. */
export function bodyToEditable(body: string): { text: string; mentions: MentionPerson[] } {
  const mentions: MentionPerson[] = []
  const text = body.replace(MENTION_RE, (_m, name: string, id: string) => {
    if (!mentions.some((p) => p.id === Number(id))) mentions.push({ id: Number(id), full_name: name, avatar: null })
    return `@${name}`
  })
  return { text, mentions }
}

/** Editable text → stored body: "@Full Name" of a picked person becomes its token. */
export function editableToBody(text: string, mentions: MentionPerson[]): string {
  let body = text
  for (const p of [...mentions].sort((a, b) => b.full_name.length - a.full_name.length)) {
    body = body.split(`@${p.full_name}`).join(`@[${p.full_name}](user:${p.id})`)
  }
  return body
}

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// ---------------------------------------------------------------- repeating tasks

export type Frequency = 'daily' | 'weekly' | 'monthly'

export interface RecurrenceInput {
  frequency: Frequency
  interval: number
  /** 0 = Monday … 6 = Sunday */
  weekdays: number[]
  monthly_mode: 'day' | 'weekday'
  month_day: number | null
  /** 1–4, or -1 for "last" */
  month_week: number | null
  month_weekday: number | null
  end_date: string | null
  count: number | null
}

export interface TaskRepeat extends RecurrenceInput {
  id: number
  start_date: string
  occurrences_created: number
  active: boolean
}

const MONDAY = Date.UTC(2026, 9, 5, 12) // a Monday; weekday i is MONDAY + i days

/** Weekday name for 0 = Monday … 6 = Sunday. */
export function weekdayName(i: number, locale: string, style: 'long' | 'short' = 'long') {
  return new Intl.DateTimeFormat(locale, { weekday: style, timeZone: 'UTC' }).format(new Date(MONDAY + i * 86_400_000))
}

/** The rule in plain words, e.g. "Every Monday and Thursday" or "Monthly on the last Friday, until 31/12/2026". */
export function describeRule(
  rule: RecurrenceInput,
  t: (key: string, options?: Record<string, unknown>) => string,
  locale: string,
  formatDate: (iso: string) => string,
) {
  const n = rule.interval || 1
  let text: string
  if (rule.frequency === 'daily') {
    text = t('tasks.repeat.rule.daily', { count: n })
  } else if (rule.frequency === 'weekly') {
    const days = new Intl.ListFormat(locale, { type: 'conjunction' }).format(rule.weekdays.map((d) => weekdayName(d, locale)))
    text = t('tasks.repeat.rule.weekly', { count: n, days })
  } else if (rule.monthly_mode === 'weekday' && rule.month_week !== null && rule.month_weekday !== null) {
    text = t('tasks.repeat.rule.monthlyWeekday', {
      count: n,
      which: t(`tasks.repeat.ordinals.${rule.month_week === -1 ? 'last' : rule.month_week}`),
      day: weekdayName(rule.month_weekday, locale),
    })
  } else {
    text = t('tasks.repeat.rule.monthlyDay', { count: n, day: rule.month_day ?? 1 })
  }
  if (rule.end_date) text += t('tasks.repeat.rule.until', { date: formatDate(`${rule.end_date}T12:00:00`) })
  else if (rule.count) text += t('tasks.repeat.rule.times', { count: rule.count })
  return text
}

/** A sensible starting rule for a due date. */
export function defaultRule(dueDate: string | null): RecurrenceInput {
  const d = dueDate ? new Date(`${dueDate}T12:00:00Z`) : new Date()
  const weekday = (d.getUTCDay() + 6) % 7
  return {
    frequency: 'weekly',
    interval: 1,
    weekdays: [weekday],
    monthly_mode: 'day',
    month_day: d.getUTCDate(),
    month_week: d.getUTCDate() > 28 ? -1 : Math.ceil(d.getUTCDate() / 7),
    month_weekday: weekday,
    end_date: null,
    count: null,
  }
}
