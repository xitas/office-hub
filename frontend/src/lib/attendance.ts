import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export type AttendanceStatus = 'present' | 'field' | 'remote' | 'leave' | 'off' | 'not_in' | 'absent' | 'upcoming'
export type AttendanceMode = 'office' | 'field' | 'remote'

export interface AttendanceDay {
  status: AttendanceStatus
  late: boolean
  check_in: string | null
  check_out: string | null
  mode: AttendanceMode | null
  note: string
  corrected: boolean
  leave: { type: string; type_ur: string; half_day: '' | 'morning' | 'afternoon' } | null
  holiday: string | null
}

export type Counts = Record<AttendanceStatus | 'late', number>

export interface TodayData {
  date: string
  me: AttendanceDay
  can_check_in: boolean
  can_check_out: boolean
  /** Managers and admins: their team's counts today. */
  team?: Counts
}

export interface MonthData {
  user: number
  user_name: string
  month: string
  days: (AttendanceDay & { date: string })[]
  totals: Counts
}

export interface TeamDayRow extends AttendanceDay {
  user: number
  user_name: string
  department: string | null
}

export interface TeamMonthData {
  month: string
  days: string[]
  rows: { user: number; user_name: string; cells: { status: AttendanceStatus; late: boolean }[]; totals: Counts }[]
}

export const ATTENDANCE_KEY = ['attendance'] as const

/** Loaded on its own (not part of /dashboard/), so the dashboard's query count stays the same. */
export function useAttendanceToday(enabled = true) {
  return useQuery({
    queryKey: [...ATTENDANCE_KEY, 'today'],
    queryFn: async () => (await api.get<TodayData>('/attendance/today/')).data,
    enabled,
    refetchInterval: 120_000,
  })
}

export function useAttendanceMonth(month: string, user?: number) {
  return useQuery({
    queryKey: [...ATTENDANCE_KEY, 'month', month, user ?? null],
    queryFn: async () => (await api.get<MonthData>('/attendance/month/', { params: { month, user } })).data,
    placeholderData: (previous) => previous,
  })
}

export function useTeamDay(date: string, department?: string, enabled = true) {
  return useQuery({
    queryKey: [...ATTENDANCE_KEY, 'team', date, department ?? null],
    queryFn: async () => (await api.get<{ date: string; rows: TeamDayRow[]; counts: Counts }>('/attendance/team/', { params: { date, department } })).data,
    enabled,
    placeholderData: (previous) => previous,
  })
}

export function useTeamMonth(month: string, department?: string, enabled = true) {
  return useQuery({
    queryKey: [...ATTENDANCE_KEY, 'team-month', month, department ?? null],
    queryFn: async () => (await api.get<TeamMonthData>('/attendance/team-month/', { params: { month, department } })).data,
    enabled,
    placeholderData: (previous) => previous,
  })
}

export const STATUS_STYLES: Record<AttendanceStatus, string> = {
  present: 'border-success/40 bg-success/10 text-success',
  field: 'border-sky-400/50 bg-sky-50 text-sky-800 dark:bg-sky-500/15 dark:text-sky-200',
  remote: 'border-violet-400/50 bg-violet-50 text-violet-800 dark:bg-violet-500/15 dark:text-violet-200',
  leave: 'border-rose-400/50 bg-rose-50 text-rose-800 dark:bg-rose-500/15 dark:text-rose-200',
  off: 'border-border bg-muted/50 text-muted-foreground',
  not_in: 'border-amber-400/50 bg-amber-50 text-amber-900 dark:bg-amber-500/15 dark:text-amber-200',
  absent: 'border-destructive/40 bg-destructive/10 text-destructive',
  upcoming: 'border-border bg-transparent text-muted-foreground',
}

/** The statuses shown as counts (in this order). */
export const COUNTED: (AttendanceStatus | 'late')[] = ['present', 'late', 'field', 'remote', 'leave', 'not_in', 'absent']
