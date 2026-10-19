import { useQuery } from '@tanstack/react-query'
import { Banknote, FileText, Package, Send, Truck, type LucideIcon } from 'lucide-react'
import { api } from './api'
import type { RecordRef } from './timeline'

export type ErrandKind = 'courier' | 'pickup' | 'delivery' | 'bank' | 'other'
export const ERRAND_KINDS: ErrandKind[] = ['courier', 'pickup', 'delivery', 'bank', 'other']
export type ErrandStatus = 'open' | 'assigned' | 'on_the_way' | 'done' | 'failed' | 'cancelled'
export const ACTIVE_ERRAND: ErrandStatus[] = ['open', 'assigned', 'on_the_way']

export const ERRAND_ICONS: Record<ErrandKind, LucideIcon> = {
  courier: Send, pickup: FileText, delivery: Truck, bank: Banknote, other: Package,
}

export const ERRAND_TONE: Record<ErrandStatus, string> = {
  open: 'border-amber-500/50 text-amber-700 dark:text-amber-300',
  assigned: 'border-teal-500/50 text-teal-700 dark:text-teal-300',
  on_the_way: 'border-sky-500/50 text-sky-700 dark:text-sky-300',
  done: 'border-success/40 text-success',
  failed: 'border-destructive/40 text-destructive',
  cancelled: 'text-muted-foreground',
}

/** Proof photos per errand (the backend checks it too). */
export const MAX_ERRAND_PHOTOS = 6

export interface ErrandPhoto {
  id: number
  original_name: string
  size: number
  width: number
  height: number
  download_url: string
  thumbnail_url: string | null
}

export interface ErrandUpdate {
  status: ErrandStatus
  note: string
  by: string | null
  at: string
}

export interface Errand {
  id: number
  title: string
  kind: ErrandKind
  details: string
  contact: RecordRef | null
  company: RecordRef | null
  vendor: RecordRef | null
  /** Who or where: the contact, company or vendor, or the place's name. */
  place: string
  place_name: string
  address: string
  city: string
  latitude: string | null
  longitude: string | null
  due_at: string | null
  assigned_to: number | null
  assigned_to_name: string | null
  requested_by: number | null
  requested_by_name: string | null
  department_name: string | null
  task: { id: number; title: string; status: string } | null
  status: ErrandStatus
  /** Tracking number, receipt or deposit slip number. */
  reference: string
  outcome_note: string
  started_at: string | null
  finished_at: string | null
  /** The viewer may open the contact or company. */
  record_visible: boolean
  updates: ErrandUpdate[]
  photos: ErrandPhoto[]
  can_change: boolean
  can_take: boolean
  can_progress: boolean
  created_at: string
}

export const ERRANDS_KEY = ['errands'] as const

export type ErrandScope = 'mine' | 'requested' | 'open' | 'team' | 'done' | 'today'

export function useErrands(query: { scope?: ErrandScope; task?: number; contact?: number; company?: number; vendor?: number }, enabled = true) {
  return useQuery({
    queryKey: [...ERRANDS_KEY, query],
    queryFn: async () => (await api.get<Errand[]>('/errands/', { params: query })).data,
    enabled,
  })
}

export function useErrand(id: number | null) {
  return useQuery({
    queryKey: [...ERRANDS_KEY, 'one', id],
    queryFn: async () => (await api.get<Errand>(`/errands/${id}/`)).data,
    enabled: !!id,
    retry: false,
  })
}

export function errandRecordLink(e: Pick<Errand, 'contact' | 'company' | 'vendor' | 'record_visible'>) {
  if (!e.record_visible) return null
  if (e.contact) return `/contacts/${e.contact.id}`
  if (e.company) return `/companies/${e.company.id}`
  if (e.vendor) return `/vendors/${e.vendor.id}`
  return null
}
