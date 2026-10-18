import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { RecordRef } from './timeline'

export type VisitPurpose = 'meeting' | 'delivery' | 'site' | 'collection' | 'support' | 'other'
export const VISIT_PURPOSES: VisitPurpose[] = ['meeting', 'delivery', 'site', 'collection', 'support', 'other']
export type VisitStatus = 'pending' | 'planned' | 'done' | 'cancelled' | 'rejected'

export interface Visit {
  id: number
  title: string
  purpose: VisitPurpose
  contact: RecordRef | null
  company: RecordRef | null
  vendor: RecordRef | null
  /** Who or where: the contact, company or vendor, or the place's name. */
  place: string
  place_name: string
  address: string
  city: string
  /** The place's pin (decimal degrees as text), for the map in a later slice. */
  latitude: string | null
  longitude: string | null
  start: string
  end: string
  assigned_to: number
  assigned_to_name: string
  department_name: string | null
  companions: RecordRef[]
  notes: string
  task: { id: number; title: string; status: string } | null
  status: VisitStatus
  decided_by_name: string | null
  decided_at: string | null
  decision_note: string
  closed_by_name: string | null
  closed_at: string | null
  close_note: string
  created_by_name: string | null
  /** The viewer may open the contact or company (a companion on a colleague's client may not). */
  record_visible: boolean
  /** Who checked in and out. Coordinates are sent only to the person, their department's managers and admins. */
  checks: VisitCheck[]
  /** I go on this visit and may check in now. */
  can_check_in: boolean
  can_change: boolean
  can_close: boolean
  can_decide: boolean
  /** How it went (everyone who can see the visit sees it). */
  report: VisitReport | null
  /** I may write or change the report now (writing it marks a planned visit done). */
  can_report: boolean
  created_at: string
}

export type ReportOutcome = 'good' | 'follow_up' | 'no_result' | 'not_met'
export const REPORT_OUTCOMES: ReportOutcome[] = ['good', 'follow_up', 'no_result', 'not_met']
export const REPORT_TONE: Record<ReportOutcome, string> = {
  good: 'border-success/40 text-success',
  follow_up: 'border-amber-500/50 text-amber-700 dark:text-amber-300',
  no_result: 'text-muted-foreground',
  not_met: 'border-destructive/40 text-destructive',
}
/** Photos per report (the backend checks it too). */
export const MAX_REPORT_PHOTOS = 8
export const PHOTO_ACCEPT = 'image/jpeg,image/png,image/webp'

export interface VisitPhoto {
  id: number
  original_name: string
  size: number
  width: number
  height: number
  /** Relative API paths, fetched with the user's token. */
  download_url: string
  thumbnail_url: string | null
}

export interface VisitReport {
  outcome: ReportOutcome
  notes: string
  next_action: string
  next_action_on: string | null
  written_by_name: string | null
  written_at: string
  updated_by_name: string | null
  updated_at: string
  photos: VisitPhoto[]
  /** The task the next action became. */
  follow_up_task: { id: number; title: string; status: string; due_date: string | null } | null
  /** The lead status moved from the report. */
  status_change: { from: string; to: string } | null
  /** Also on the contact's, company's or vendor's timeline (not for a visit to a place). */
  on_timeline: boolean
}

export type CheckLocation = 'recorded' | 'declined' | 'unavailable'

export interface CheckSpot {
  latitude: string
  longitude: string
  /** Metres, as the device reported it. */
  accuracy: number | null
  /** From the visit's pin, when both exist (information only). */
  distance_m: number | null
}

export interface VisitCheck {
  user: number
  user_name: string
  checked_in_at: string
  checked_out_at: string | null
  in_location: CheckLocation
  out_location: CheckLocation | ''
  /** Coordinates removed after 90 days. */
  location_removed: boolean
  /** May I see where they were? (if not, in/out are null) */
  location_visible: boolean
  in: CheckSpot | null
  out: CheckSpot | null
}

export const VISITS_KEY = ['visits'] as const

export type VisitQuery =
  | { scope: 'mine'; when: 'upcoming' | 'past' }
  | { scope: 'team'; from: string; to: string; person?: string }
  | { scope: 'approvals' }
  | { scope: 'today' }
  | { contact?: number; company?: number; vendor?: number; task?: number }

export function useVisits(query: VisitQuery, enabled = true) {
  return useQuery({
    queryKey: [...VISITS_KEY, 'list', query],
    queryFn: async () => (await api.get<Visit[]>('/visits/', { params: query })).data,
    enabled,
    placeholderData: (previous) => previous,
  })
}

export function useVisit(id: number | null) {
  return useQuery({
    queryKey: [...VISITS_KEY, 'one', id],
    queryFn: async () => (await api.get<Visit>(`/visits/${id}/`)).data,
    enabled: id !== null,
  })
}

export interface VisitPeople {
  plan_for: { id: number; name: string; department: number | null }[]
  companions: { id: number; name: string; department: number | null }[]
}

export function useVisitPeople() {
  return useQuery({
    queryKey: [...VISITS_KEY, 'people'],
    queryFn: async () => (await api.get<VisitPeople>('/visits/people/')).data,
    staleTime: 5 * 60_000,
  })
}

export const VISIT_TONE: Record<VisitStatus, string> = {
  pending: 'border-amber-500/50 text-amber-700 dark:text-amber-300',
  planned: 'border-teal-500/50 text-teal-700 dark:text-teal-300',
  done: 'border-success/40 text-success',
  cancelled: 'text-muted-foreground',
  rejected: 'border-destructive/40 text-destructive',
}

/** Where a visit's record lives in the app, if it's a contact, company or vendor. */
export function visitRecordLink(v: Pick<Visit, 'contact' | 'company' | 'vendor' | 'record_visible'>) {
  if (!v.record_visible) return null
  if (v.contact) return `/contacts/${v.contact.id}`
  if (v.company) return `/companies/${v.company.id}`
  if (v.vendor) return `/vendors/${v.vendor.id}`
  return null
}
