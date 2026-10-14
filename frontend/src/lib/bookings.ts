import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { officeDate } from './tasks'

export const RESOURCE_TYPES = ['room', 'projector', 'vehicle', 'other'] as const
export type ResourceType = (typeof RESOURCE_TYPES)[number]
export type BookingStatus = 'confirmed' | 'pending' | 'rejected' | 'cancelled'

export interface Resource {
  id: number
  name: string
  type: ResourceType
  capacity: number | null
  location: string
  description: string
  bookable_by: 'everyone' | 'departments'
  departments: number[]
  department_names: string[]
  needs_approval: boolean
  is_active: boolean
  photo_url: string | null
  thumbnail_url: string | null
}

export interface Booking {
  id: number
  resource: number
  resource_name: string
  resource_type: ResourceType
  title: string
  start: string
  end: string
  booked_by: number
  booked_by_name: string
  attendees: number[]
  attendee_details: { id: number; full_name: string }[]
  notes: string
  status: BookingStatus
  series: number | null
  is_series: boolean
  decided_by_name: string | null
  decided_at: string | null
  decision_reason: string
  can_edit: boolean
  can_decide: boolean
  created_at: string
}

export interface Occurrence {
  start: string
  end: string
  problem: 'conflict' | 'rules' | null
  message: string
  conflict: { id: number; title: string; booked_by_name: string } | null
}

export const BOOKINGS_KEY = ['bookings'] as const
export const RESOURCES_KEY = ['resources'] as const
export const SLOT_MINUTES = 15

export function useResources(params: { active?: boolean } = {}) {
  return useQuery({
    queryKey: [...RESOURCES_KEY, params],
    queryFn: async () => (await api.get<Resource[]>('/resources/', { params: { active: params.active ? 1 : undefined } })).data,
    staleTime: 60_000,
  })
}

/** Holding bookings (confirmed and pending) of the resources I can see, for office days `from`..`to`. */
export function useBookingsRange(from: string, to: string, resource?: number) {
  return useQuery({
    queryKey: [...BOOKINGS_KEY, 'range', from, to, resource ?? null],
    queryFn: async () => (await api.get<Booking[]>('/bookings/', { params: { from, to, resource } })).data,
    placeholderData: (previous) => previous,
  })
}

export function useMyBookings(when: 'upcoming' | 'past') {
  return useQuery({
    queryKey: [...BOOKINGS_KEY, 'mine', when],
    queryFn: async () => (await api.get<Booking[]>('/bookings/', { params: { mine: 1, when } })).data,
  })
}

export function useApprovals(enabled: boolean) {
  return useQuery({
    queryKey: [...BOOKINGS_KEY, 'approvals'],
    queryFn: async () => (await api.get<Booking[]>('/bookings/', { params: { approvals: 1 } })).data,
    enabled,
  })
}

// ------------------------------------------------------------------ office-time helpers
// Bookings live in the office's time zone (Organization page), whatever the browser's zone is.

function parts(timeZone: string, at: Date) {
  const f = new Intl.DateTimeFormat('en-GB', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  })
  const p = Object.fromEntries(f.formatToParts(at).map((x) => [x.type, x.value]))
  return { date: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}` }
}

/** Office-clock date ("YYYY-MM-DD") and time ("HH:MM") of a moment. */
export function officeParts(timeZone: string, iso: string | Date) {
  return parts(timeZone, typeof iso === 'string' ? new Date(iso) : iso)
}

/** The moment (ISO, UTC) for an office-clock date and time. */
export function officeMoment(timeZone: string, date: string, time: string): string {
  const [y, m, d] = date.split('-').map(Number)
  const [hh, mm] = time.split(':').map(Number)
  const wall = Date.UTC(y, m - 1, d, hh, mm)
  // The zone's offset at that wall time (checked twice so a DST change in between is handled).
  let guess = wall
  for (let i = 0; i < 2; i++) {
    const seen = parts(timeZone, new Date(guess))
    const [sy, sm, sd] = seen.date.split('-').map(Number)
    const [sh, smin] = seen.time.split(':').map(Number)
    guess += wall - Date.UTC(sy, sm - 1, sd, sh, smin)
  }
  return new Date(guess).toISOString()
}

export function minutesOf(time: string) {
  const [h, m] = time.slice(0, 5).split(':').map(Number)
  return h * 60 + m
}

export function timeOf(minutes: number) {
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
}

export function addDays(date: string, days: number) {
  const d = new Date(`${date}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

/** Monday-or-whatever week start on or before `date` (0 = Sunday … 6 = Saturday, as in OrgSettings). */
export function weekStartOf(date: string, weekStart: number) {
  const day = new Date(`${date}T12:00:00Z`).getUTCDay()
  return addDays(date, -((day - weekStart + 7) % 7))
}

export function todayInOffice(timeZone: string) {
  return officeDate(timeZone)
}

/** 0 = Monday … 6 = Sunday (the backend's weekday numbering) for a date. */
export function isoWeekday(date: string) {
  return (new Date(`${date}T12:00:00Z`).getUTCDay() + 6) % 7
}

export interface Placed {
  booking: Booking
  start: number // minutes after midnight, office time
  end: number
}

/** Bookings of one resource on one office day, as minute ranges. */
export function placeBookings(bookings: Booking[], resource: number, date: string, tz: string): Placed[] {
  return bookings
    .filter((b) => b.resource === resource)
    .map((b) => {
      const s = officeParts(tz, b.start)
      const e = officeParts(tz, b.end)
      return { booking: b, sDate: s.date, start: minutesOf(s.time), end: e.date === s.date ? minutesOf(e.time) : 24 * 60 }
    })
    .filter((p) => p.sDate === date)
    .map(({ booking, start, end }) => ({ booking, start, end }))
}

/** Free time between bookings within office hours (and not already past). */
export function freeRanges(placed: Placed[], opens: number, closes: number, notBefore = 0): [number, number][] {
  const free: [number, number][] = []
  let cursor = Math.max(opens, Math.ceil(notBefore / SLOT_MINUTES) * SLOT_MINUTES)
  for (const p of [...placed].sort((a, b) => a.start - b.start)) {
    if (p.start > cursor) free.push([cursor, Math.min(p.start, closes)])
    cursor = Math.max(cursor, p.end)
  }
  if (cursor < closes) free.push([cursor, closes])
  return free.filter(([s, e]) => e - s >= SLOT_MINUTES)
}
