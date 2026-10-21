import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { addDays, weekStartOf } from './bookings'

export type ReportKey = 'task-completion' | 'overdue-tasks' | 'client-interactions' | 'lead-pipeline' | 'field-visits' | 'errands'
export const REPORTS: ReportKey[] = ['task-completion', 'overdue-tasks', 'client-interactions', 'lead-pipeline', 'field-visits', 'errands']
/** Reports that cover a period (the others are "as of today"). */
export const PERIOD_REPORTS: ReportKey[] = ['task-completion', 'client-interactions', 'lead-pipeline', 'field-visits', 'errands']

export type PeriodPreset = 'this_week' | 'last_week' | 'this_month' | 'last_month' | 'this_quarter' | 'last_quarter' | 'this_year' | 'custom'
export const PERIOD_PRESETS: PeriodPreset[] = ['this_week', 'last_week', 'this_month', 'last_month', 'this_quarter', 'last_quarter', 'this_year', 'custom']

const iso = (y: number, m: number, d: number) => new Date(Date.UTC(y, m, d)).toISOString().slice(0, 10)

/** A preset's first and last office day, from today's office date and the office's week start. */
export function presetRange(preset: Exclude<PeriodPreset, 'custom'>, today: string, weekStart: number): { from: string; to: string } {
  const [y, m] = today.split('-').map(Number)
  const month = m - 1
  const quarter = Math.floor(month / 3) * 3
  switch (preset) {
    case 'this_week': {
      const from = weekStartOf(today, weekStart)
      return { from, to: addDays(from, 6) }
    }
    case 'last_week': {
      const from = addDays(weekStartOf(today, weekStart), -7)
      return { from, to: addDays(from, 6) }
    }
    case 'this_month':
      return { from: iso(y, month, 1), to: iso(y, month + 1, 0) }
    case 'last_month':
      return { from: iso(y, month - 1, 1), to: iso(y, month, 0) }
    case 'this_quarter':
      return { from: iso(y, quarter, 1), to: iso(y, quarter + 3, 0) }
    case 'last_quarter':
      return { from: iso(y, quarter - 3, 1), to: iso(y, quarter, 0) }
    case 'this_year':
      return { from: iso(y, 0, 1), to: iso(y, 11, 31) }
  }
}

export interface CompletionRow {
  id: number | null
  name: string | null
  department?: string | null
  due: number
  done: number
  on_time: number
  late: number
  overdue: number
  open: number
  completed: number
  /** 0–1, or null when nothing was due. */
  rate: number | null
  on_time_rate: number | null
}

export interface CompletionReport {
  from: string
  to: string
  as_of: string
  people: CompletionRow[]
  departments: CompletionRow[]
  totals: CompletionRow
  scope: { department: number | null; person: number | null }
}

export interface OverduePerson {
  id: number
  name: string
  department: string | null
  overdue: number
  urgent: number
  oldest: string | null
  days_1_7: number
  days_8_30: number
  days_31_plus: number
}

export interface OverdueTask {
  id: number
  title: string
  due_date: string
  days_late: number
  priority: string
  status: string
  record: string | null
  assignees: string[]
}

export interface OverdueReport {
  as_of: string
  people: OverduePerson[]
  total: number
  tasks: OverdueTask[]
}

export interface ReportFilters {
  from?: string
  to?: string
  department?: string
  person?: string
  /** Client interactions: by office week or month. */
  by?: string
}

const clean = (f: ReportFilters) => Object.fromEntries(Object.entries(f).filter(([, v]) => v))

export function useCompletionReport(filters: ReportFilters) {
  return useQuery({
    queryKey: ['reports', 'task-completion', clean(filters)],
    queryFn: async () => (await api.get<CompletionReport>('/reports/task-completion/', { params: clean(filters) })).data,
  })
}

export function useOverdueReport(filters: ReportFilters, enabled: boolean) {
  return useQuery({
    queryKey: ['reports', 'overdue-tasks', clean(filters)],
    queryFn: async () => (await api.get<OverdueReport>('/reports/overdue-tasks/', { params: clean(filters) })).data,
    enabled,
  })
}

export function useReportPeople(department?: string) {
  return useQuery({
    queryKey: ['reports', 'people', department ?? ''],
    queryFn: async () => (await api.get<{ people: { id: number; name: string; department: number | null }[]; department: number | null }>(
      '/reports/people/', { params: department ? { department } : {} })).data,
    staleTime: 5 * 60_000,
  })
}

/** A 0–1 fraction as a whole percentage, rounded half up (as in the exports); "—" when there's nothing to divide. */
export const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)

export const exportParams = (filters: ReportFilters, file: 'pdf' | 'xlsx') => ({ ...clean(filters), file })

// ================================================================ client reports (slice 2)

export type InteractionKind = 'call' | 'meeting' | 'email' | 'whatsapp' | 'visit'

export interface InteractionBucket {
  from: string
  to: string
  counts: Record<InteractionKind, number>
  total: number
}

export interface InteractionsReport {
  from: string
  to: string
  by: 'week' | 'month'
  kinds: InteractionKind[]
  buckets: InteractionBucket[]
  people: { id: number; name: string; department: string | null; counts: Record<InteractionKind, number>; total: number; clients: number }[]
  totals: { counts: Record<InteractionKind, number>; total: number; clients: number }
}

export interface FunnelRow {
  id?: number | null
  name?: string | null
  department?: string | null
  created: number
  contacted: number
  in_discussion: number
  won: number
  lost: number
  open: number
  win_rate: number | null
  conversion: number | null
}

export interface PipelineReport {
  from: string
  to: string
  funnel: FunnelRow
  people: FunnelRow[]
  moves: { from: string; to: string; count: number }[]
  won_in_period: number
  average_days_to_win: number | null
}

export function useInteractionsReport(filters: ReportFilters & { by?: string }) {
  return useQuery({
    queryKey: ['reports', 'client-interactions', clean(filters)],
    queryFn: async () => (await api.get<InteractionsReport>('/reports/client-interactions/', { params: clean(filters) })).data,
  })
}

export function usePipelineReport(filters: ReportFilters) {
  return useQuery({
    queryKey: ['reports', 'lead-pipeline', clean(filters)],
    queryFn: async () => (await api.get<PipelineReport>('/reports/lead-pipeline/', { params: clean(filters) })).data,
  })
}

// ================================================================ field reports (slice 3)

export type VisitPurposeKey = 'meeting' | 'delivery' | 'site' | 'collection' | 'support' | 'other'
export type VisitOutcomeKey = 'good' | 'follow_up' | 'no_result' | 'not_met'

export interface VisitRow {
  id?: number | null
  name?: string | null
  purpose?: VisitPurposeKey
  scheduled: number
  done: number
  cancelled: number
  not_closed: number
  upcoming: number
  checked_in: number
  reported: number
  /** Done out of those whose time has come (done, cancelled, not closed). */
  completion: number | null
  check_in_rate: number | null
  report_rate: number | null
}

export interface FieldVisitsReport {
  from: string
  to: string
  people: VisitRow[]
  purposes: VisitRow[]
  outcomes: { outcome: VisitOutcomeKey; count: number; share: number | null }[]
  totals: VisitRow
}

export interface ErrandRow {
  id?: number | null
  name?: string | null
  kind?: string
  asked: number
  done: number
  failed: number
  cancelled: number
  open: number
  overdue: number
  on_time: number
  success: number | null
  on_time_rate: number | null
}

export interface ErrandsReport {
  from: string
  to: string
  people: ErrandRow[]
  kinds: ErrandRow[]
  totals: ErrandRow
}

export function useFieldVisitsReport(filters: ReportFilters) {
  return useQuery({
    queryKey: ['reports', 'field-visits', clean(filters)],
    queryFn: async () => (await api.get<FieldVisitsReport>('/reports/field-visits/', { params: clean(filters) })).data,
  })
}

export function useErrandsReport(filters: ReportFilters) {
  return useQuery({
    queryKey: ['reports', 'errands', clean(filters)],
    queryFn: async () => (await api.get<ErrandsReport>('/reports/errands/', { params: clean(filters) })).data,
  })
}
