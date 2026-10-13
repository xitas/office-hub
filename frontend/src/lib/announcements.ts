import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { ChatAttachment } from './chat'
import type { Paginated } from './types'

export type AnnouncementAudience = 'everyone' | 'departments'

export interface Announcement {
  id: number
  title: string
  /** Light formatting: **bold**, "- " / "1. " lists, [text](url) and bare links. */
  body: string
  audience: AnnouncementAudience
  departments: number[]
  department_names: string[]
  pinned: boolean
  expires_on: string | null
  expired: boolean
  created_by: number | null
  created_by_name: string | null
  published_at: string
  updated_at: string
  attachments: ChatAttachment[]
  is_read: boolean
  can_edit: boolean
  /** Author and admins only. */
  receipts: { read: number; total: number } | null
}

export interface ReceiptPerson {
  id: number
  full_name: string
  department: string | null
  read_at?: string
}

export interface Receipts {
  read_count: number
  total: number
  read: ReceiptPerson[]
  unread: ReceiptPerson[]
}

export interface AnnouncementsWidget {
  unread: number
  items: { id: number; title: string; pinned: boolean; author: string | null; published_at: string; preview: string; url: string }[]
}

export const ANNOUNCEMENTS_KEY = ['announcements'] as const

export function useAnnouncements(filters: { archive?: boolean; q?: string; page?: number }) {
  return useQuery({
    queryKey: [...ANNOUNCEMENTS_KEY, 'list', filters],
    queryFn: async () =>
      (
        await api.get<Paginated<Announcement>>('/announcements/', {
          params: { archive: filters.archive ? 1 : undefined, q: filters.q || undefined, page: filters.page },
        })
      ).data,
    placeholderData: (previous) => previous,
  })
}

export function useAnnouncement(id: number) {
  return useQuery({
    queryKey: [...ANNOUNCEMENTS_KEY, 'detail', id],
    queryFn: async () => (await api.get<Announcement>(`/announcements/${id}/`)).data,
  })
}

export function useReceipts(id: number, enabled: boolean) {
  return useQuery({
    queryKey: [...ANNOUNCEMENTS_KEY, 'receipts', id],
    queryFn: async () => (await api.get<Receipts>(`/announcements/${id}/receipts/`)).data,
    enabled,
  })
}

/** Text direction from the first strong letter, so an Urdu announcement reads right to left in any interface language. */
export function textDir(text: string): 'rtl' | 'ltr' {
  const m = /[A-Za-z֐-ࣿיִ-﷿ﹰ-﻿]/.exec(text)
  return m && /[֐-ࣿיִ-﷿ﹰ-﻿]/.test(m[0]) ? 'rtl' : 'ltr'
}
