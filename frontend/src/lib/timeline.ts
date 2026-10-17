import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CalendarDays, CheckSquare, CirclePlus, FileUp, Mail, MessageCircle, NotebookPen, Phone, Repeat2, type LucideIcon } from 'lucide-react'
import { api } from './api'
import type { ContactStatus } from './types'

/** Entry types people log by hand. Later modules add theirs here and in the backend registry. */
export const ENTRY_KINDS = ['note', 'call', 'meeting', 'email', 'whatsapp'] as const
/** Kinds that count as being in touch with the client ("Last contacted"); a note is internal. */
export const CONTACT_KINDS = ['call', 'meeting', 'email', 'whatsapp'] as const
/** A lead with no contact for this many days gets a "No contact in N days" hint. */
export const STALE_AFTER_DAYS = 14
export type EntryKind = (typeof ENTRY_KINDS)[number]
/** Everything the timeline can show, including automatic entries. */
export const TIMELINE_FILTERS = [...ENTRY_KINDS, 'task', 'status', 'created', 'imported'] as const

export const CALL_DIRECTIONS = ['out', 'in'] as const
export const CALL_OUTCOMES = ['connected', 'no_answer', 'busy', 'voicemail', 'wrong_number'] as const

export interface CallDetails {
  direction?: (typeof CALL_DIRECTIONS)[number]
  outcome?: (typeof CALL_OUTCOMES)[number]
  duration_minutes?: number
}

export interface EmailDetails {
  direction?: (typeof CALL_DIRECTIONS)[number]
  subject?: string
}

export interface WhatsAppDetails {
  direction?: (typeof CALL_DIRECTIONS)[number]
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
  /** The task made for this follow-up, if any. */
  follow_up_task?: { id: number; status: string; assignees: string[] } | null
  /** Its task was completed. */
  follow_up_done?: boolean
  /** The person chose not to make a task for it. */
  follow_up_skipped?: boolean
  created_by_name: string | null
  created_at: string
  updated_at: string
  editable: boolean
  contact: RecordRef | null
  company: RecordRef | null
  /** Calls, messages and notes with a supplier (vendors are shared office-wide). */
  vendor?: RecordRef | null
}

export type TimelineTarget = { contact: number } | { company: number } | { vendor: number }

/** The page of the record a target points at. */
export function targetPath(target: TimelineTarget) {
  if ('contact' in target) return `/contacts/${target.contact}`
  return 'company' in target ? `/companies/${target.company}` : `/vendors/${target.vendor}`
}

/** A stable key for a target ("contact-3", "vendor-7"). */
export function targetKey(target: TimelineTarget) {
  if ('contact' in target) return `contact-${target.contact}`
  return 'company' in target ? `company-${target.company}` : `vendor-${target.vendor}`
}

export interface EntryInput {
  kind: EntryKind
  summary: string
  details: CallDetails | MeetingDetails | EmailDetails | WhatsAppDetails | Record<string, never>
  occurred_at: string
  follow_up_on: string | null
  /** Who the follow-up task goes to (default: you). */
  follow_up_assignee?: number | null
  /** No task for this follow-up. */
  follow_up_skip?: boolean
}

/** Filters of the communication log page (all optional). */
export interface LogFilters {
  type?: string
  direction?: string
  logged_by?: string
  contact?: string
  company?: string
  vendor?: string
  date_from?: string
  date_to?: string
  follow_up?: string
  q?: string
}

/** Whole days since a moment (0 = today). */
export function daysSince(iso: string) {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000))
}

/** "No contact in N days" for an open lead: since the last call/meeting/email/WhatsApp, or since it was added. */
export function staleDays(lead: { status: string; last_contacted_at?: string | null; created_at?: string }) {
  if (lead.status === 'won' || lead.status === 'lost') return null
  const since = lead.last_contacted_at ?? lead.created_at
  if (!since) return null
  const days = daysSince(since)
  return days >= STALE_AFTER_DAYS ? days : null
}

export const KIND_ICONS: Record<string, LucideIcon> = {
  note: NotebookPen,
  call: Phone,
  meeting: CalendarDays,
  email: Mail,
  whatsapp: MessageCircle,
  status: Repeat2,
  created: CirclePlus,
  imported: FileUp,
  task: CheckSquare,
}

export const KIND_STYLES: Record<string, string> = {
  note: 'bg-primary/10 text-primary',
  call: 'bg-success/15 text-success',
  meeting: 'bg-warning/20 text-foreground',
  email: 'bg-sky-500/15 text-sky-700 dark:text-sky-300',
  whatsapp: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
  status: 'bg-muted text-muted-foreground',
  created: 'bg-muted text-muted-foreground',
  imported: 'bg-muted text-muted-foreground',
  task: 'bg-primary/10 text-primary',
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
