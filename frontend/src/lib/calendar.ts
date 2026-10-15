import { useQuery } from '@tanstack/react-query'
import {
  addDays as addDaysFns,
  addMonths,
  addWeeks,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  parseISO,
  startOfMonth,
  startOfWeek,
} from 'date-fns'
import { api } from './api'
import { useMe } from './auth'

// ------------------------------------------------------------------ shared by the task and office calendars

export type CalendarMode = 'month' | 'week' | 'day'
export const isoDay = (d: Date) => format(d, 'yyyy-MM-dd')

/** The days a month (whole weeks), week or day view shows, for an anchor day ("YYYY-MM-DD"). */
export function calendarRange(anchor: string, mode: CalendarMode, weekStartsOn: 0 | 1 | 6) {
  const a = parseISO(anchor)
  const first = mode === 'month' ? startOfWeek(startOfMonth(a), { weekStartsOn }) : mode === 'week' ? startOfWeek(a, { weekStartsOn }) : a
  const last = mode === 'month' ? endOfWeek(endOfMonth(a), { weekStartsOn }) : mode === 'week' ? endOfWeek(a, { weekStartsOn }) : a
  return { start: isoDay(first), end: isoDay(last), days: eachDayOfInterval({ start: first, end: last }) }
}

/** The anchor one step back or forward (a month, a week or a day). */
export function stepAnchor(anchor: string, mode: CalendarMode, dir: 1 | -1) {
  const a = parseISO(anchor)
  return isoDay(mode === 'month' ? addMonths(a, dir) : mode === 'week' ? addWeeks(a, dir) : addDaysFns(a, dir))
}

/** Calendar days formatted at UTC noon, so no time zone can shift the day. */
export const dayDate = (d: string) => new Date(`${d}T12:00:00Z`)

export function calendarTitles(locale: string, anchor: string, range: { start: string; end: string }) {
  const month = new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric', timeZone: 'UTC', numberingSystem: 'latn' }).format(dayDate(anchor))
  // Compact, so it fits next to the controls on phones: "5–11 Oct 2026", "29 Sept – 5 Oct 2026".
  const week = new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC', numberingSystem: 'latn' })
    .formatRange(dayDate(range.start), dayDate(range.end))
  const longDay = (d: string) =>
    new Intl.DateTimeFormat(locale, { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC', numberingSystem: 'latn' }).format(dayDate(d))
  const weekday = (d: string, style: 'short' | 'long') => new Intl.DateTimeFormat(locale, { weekday: style, timeZone: 'UTC' }).format(dayDate(d))
  return { month, week, longDay, weekday }
}

// ------------------------------------------------------------------ the office calendar

export type CalendarItemType = 'meeting' | 'event' | 'holiday' | 'task' | 'booking' | 'leave'
export const CALENDAR_LAYERS = ['meetings', 'events', 'holidays', 'tasks', 'bookings', 'leave'] as const
export type CalendarLayer = (typeof CALENDAR_LAYERS)[number]
export const LAYER_OF: Record<CalendarItemType, CalendarLayer> = {
  meeting: 'meetings', event: 'events', holiday: 'holidays', task: 'tasks', booking: 'bookings', leave: 'leave',
}

export interface CalendarItem {
  key: string
  type: CalendarItemType
  id: number
  title: string
  start: string
  end: string
  all_day: boolean
  /** All-day items: first and last office day (inclusive). */
  start_date?: string
  end_date?: string
  location?: string
  room?: string | null
  room_status?: string | null
  organizer?: string | null
  attendee_count?: number
  can_edit?: boolean
  priority?: string
  status?: string
  is_overdue?: boolean
  /** Leave: the leave type (the title is the person). */
  subtitle?: string
  url: string | null
}

export interface OfficeEvent {
  id: number
  kind: 'meeting' | 'event' | 'holiday'
  title: string
  description: string
  location: string
  all_day: boolean
  start: string
  end: string
  start_date: string | null
  end_date: string | null
  organizer: number | null
  organizer_name: string | null
  attendees: number[]
  attendee_details: { id: number; full_name: string }[]
  audience: 'everyone' | 'departments'
  departments: number[]
  department_names: string[]
  /** The room booking behind a meeting's room. */
  booking: number | null
  room: number | null
  room_name: string | null
  room_status: string | null
  can_edit: boolean
}

export const CALENDAR_KEY = ['calendar'] as const

/** Kinds this person may add: meetings (anyone), office events (managers, admins), holidays (admins). */
export function useAllowedKinds(): OfficeEvent['kind'][] {
  const me = useMe()
  return me.role === 'admin' ? ['meeting', 'event', 'holiday'] : me.role === 'manager' && me.department ? ['meeting', 'event'] : ['meeting']
}

export function useCalendar(from: string, to: string, layers: CalendarLayer[]) {
  return useQuery({
    queryKey: [...CALENDAR_KEY, from, to, layers.join(',')],
    queryFn: async () =>
      (await api.get<{ today: string; items: CalendarItem[] }>('/calendar/', { params: { from, to, layers: layers.join(',') } })).data,
    placeholderData: (previous) => previous,
  })
}

export function useOfficeEvent(id: number | null) {
  return useQuery({
    queryKey: [...CALENDAR_KEY, 'event', id],
    queryFn: async () => (await api.get<OfficeEvent>(`/events/${id}/`)).data,
    enabled: !!id,
  })
}

/** Office days an item covers within [start, end] ("YYYY-MM-DD" strings). */
export function itemDays(item: CalendarItem, officeDayOf: (iso: string) => string): [string, string] {
  if (item.all_day && item.start_date && item.end_date) return [item.start_date, item.end_date]
  const first = officeDayOf(item.start)
  // An item ending exactly at midnight belongs to the day before.
  const endMoment = new Date(new Date(item.end).getTime() - 1).toISOString()
  return [first, officeDayOf(endMoment) < first ? first : officeDayOf(endMoment)]
}

export const TYPE_STYLES: Record<CalendarItemType, string> = {
  meeting: 'border-primary/40 bg-primary/10 text-primary dark:bg-primary/20',
  event: 'border-violet-400/50 bg-violet-50 text-violet-800 dark:bg-violet-500/15 dark:text-violet-200',
  holiday: 'border-emerald-400/50 bg-emerald-50 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200',
  task: 'border-amber-400/50 bg-amber-50 text-amber-900 dark:bg-amber-500/15 dark:text-amber-200',
  booking: 'border-sky-400/50 bg-sky-50 text-sky-800 dark:bg-sky-500/15 dark:text-sky-200',
  leave: 'border-rose-400/50 bg-rose-50 text-rose-800 dark:bg-rose-500/15 dark:text-rose-200',
}
export const TYPE_DOTS: Record<CalendarItemType, string> = {
  meeting: 'bg-primary', event: 'bg-violet-500', holiday: 'bg-emerald-500', task: 'bg-amber-500', booking: 'bg-sky-500', leave: 'bg-rose-500',
}
