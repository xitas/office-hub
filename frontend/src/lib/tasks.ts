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
