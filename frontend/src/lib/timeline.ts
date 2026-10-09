import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CalendarDays, CirclePlus, NotebookPen, Phone, Repeat2, type LucideIcon } from 'lucide-react'
import { api } from './api'
import type { ContactStatus } from './types'

/** Entry types people log by hand. Later modules add theirs here and in the backend registry. */
export const ENTRY_KINDS = ['note', 'call', 'meeting'] as const
export type EntryKind = (typeof ENTRY_KINDS)[number]
/** Everything the timeline can show, including automatic entries. */
export const TIMELINE_FILTERS = [...ENTRY_KINDS, 'status', 'created'] as const

export const CALL_DIRECTIONS = ['out', 'in'] as const
export const CALL_OUTCOMES = ['connected', 'no_answer', 'busy', 'voicemail', 'wrong_number'] as const

export interface CallDetails {
  direction?: (typeof CALL_DIRECTIONS)[number]
  outcome?: (typeof CALL_OUTCOMES)[number]
  duration_minutes?: number
}

export interface MeetingDetails {
  location?: string
  attendees?: string
}

export interface StatusDetails {
  from: ContactStatus
  to: ContactStatus
}

export interface CreatedDetails {
  record: 'contact' | 'company'
  status?: ContactStatus | null
}

export interface RecordRef {
  id: number
  name: string
}

export interface TimelineItem {
  /** Unique across stored and automatic entries, e.g. "entry:12" or "status:40". */
  id: string
  /** Set for stored entries (used to edit/delete). */
  entry_id: number | null
  kind: string
  source: 'manual' | 'auto'
  summary: string
  details: Record<string, unknown>
  occurred_at: string
  follow_up_on: string | null
  created_by_name: string | null
  created_at: string
  updated_at: string
  editable: boolean
  contact: RecordRef | null
  company: RecordRef | null
}

export type TimelineTarget = { contact: number } | { company: number }

export interface EntryInput {
  kind: EntryKind
  summary: string
  details: CallDetails | MeetingDetails | Record<string, never>
  occurred_at: string
  follow_up_on: string | null
}

export const KIND_ICONS: Record<string, LucideIcon> = {
  note: NotebookPen,
  call: Phone,
  meeting: CalendarDays,
  status: Repeat2,
  created: CirclePlus,
}

export const KIND_STYLES: Record<string, string> = {
  note: 'bg-primary/10 text-primary',
  call: 'bg-success/15 text-success',
  meeting: 'bg-warning/20 text-foreground',
  status: 'bg-muted text-muted-foreground',
  created: 'bg-muted text-muted-foreground',
}


/** <input type="datetime-local"> value for a moment, in the browser's time zone. */
export function toLocalInput(value: Date | string) {
  const d = new Date(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** Creates a timeline entry and refreshes every timeline on screen. */
export function useAddEntry() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: Partial<EntryInput> & TimelineTarget) => (await api.post<TimelineItem>('/timeline/', input)).data,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['timeline'] }),
  })
}
