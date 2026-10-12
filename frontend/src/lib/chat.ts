import { useQuery, type InfiniteData, type QueryClient } from '@tanstack/react-query'
import { api } from './api'
import { useMe } from './auth'

export interface ChatPerson {
  id: number
  full_name: string
  avatar: string | null
}

export interface ChatMessage {
  id: number
  conversation: number
  author: ChatPerson | null
  body: string
  reply_to: number | null
  created_at: string
  edited_at: string | null
  deleted: boolean
  editable_until: string | null
}

export interface Conversation {
  id: number
  kind: 'channel' | 'direct'
  name: string
  description: string
  channel_type: 'general' | 'department' | 'project' | ''
  is_private: boolean
  is_default: boolean
  department: number | null
  department_name: string | null
  archived: boolean
  is_member: boolean
  member_count: number
  unread_count: number
  last_message: { id: number; author: ChatPerson | null; body: string; deleted: boolean; created_at: string } | null
  last_message_at: string | null
  other_person: ChatPerson | null
  can_manage: boolean
  can_post: boolean
}

export interface MessagePage {
  next: string | null
  previous: string | null
  results: ChatMessage[]
}

/** Live events pushed over the shared WebSocket (only to members). */
export type ChatEvent =
  | { type: 'chat'; event: 'message.new' | 'message.updated'; conversation: number; message: ChatMessage; unread: number }
  | { type: 'chat'; event: 'read'; conversation: number; unread: number }
  | { type: 'chat'; event: 'conversation.changed'; conversation: number }

export const CONVERSATIONS_KEY = ['chat', 'conversations'] as const
export const CHAT_UNREAD_KEY = ['chat', 'unread'] as const
export const messagesKey = (id: number) => ['chat', 'messages', id] as const

/** The conversations you belong to, newest activity first (kept current by live events). */
export function useConversations() {
  return useQuery({
    queryKey: [...CONVERSATIONS_KEY, 'mine'],
    queryFn: async () => (await api.get<Conversation[]>('/chat/conversations/')).data,
  })
}

export function useChatUnread() {
  const me = useMe()
  const allowed = me.permissions.includes('chat.view')
  const { data } = useQuery({
    queryKey: CHAT_UNREAD_KEY,
    queryFn: async () => (await api.get<{ count: number }>('/chat/conversations/unread/')).data,
    enabled: allowed,
    staleTime: 60_000,
  })
  return allowed ? (data?.count ?? 0) : 0
}

/** The `cursor` value from a pagination link (links point at the API host, so only the cursor is reused). */
export function cursorOf(link: string | null) {
  if (!link) return undefined
  return new URL(link, window.location.origin).searchParams.get('cursor') ?? undefined
}

/** Apply a live chat event to the cached conversation list, unread badge and open message history. */
export function applyChatEvent(queryClient: QueryClient, event: ChatEvent) {
  if (event.event === 'conversation.changed') {
    void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_KEY })
    void queryClient.invalidateQueries({ queryKey: CHAT_UNREAD_KEY })
    return
  }
  // Per-conversation unread count -> list and the total badge.
  let known = false
  queryClient.setQueryData<Conversation[]>([...CONVERSATIONS_KEY, 'mine'], (list) => {
    if (!list) return list
    return list
      .map((c) => {
        if (c.id !== event.conversation) return c
        known = true
        const updated = { ...c, unread_count: event.unread }
        if (event.event === 'message.new') {
          const m = event.message
          updated.last_message = { id: m.id, author: m.author, body: m.body.slice(0, 120), deleted: m.deleted, created_at: m.created_at }
          updated.last_message_at = m.created_at
        } else if (event.event === 'message.updated' && c.last_message?.id === event.message.id) {
          updated.last_message = { ...c.last_message, body: event.message.body.slice(0, 120), deleted: event.message.deleted }
        }
        return updated
      })
      .sort((a, b) => (b.last_message_at ?? '').localeCompare(a.last_message_at ?? ''))
  })
  if (!known) void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_KEY })
  void queryClient.invalidateQueries({ queryKey: CHAT_UNREAD_KEY })

  if (event.event === 'read') return
  // Newest page first; pages are newest-first lists.
  queryClient.setQueryData<InfiniteData<MessagePage>>(messagesKey(event.conversation), (data) => {
    if (!data) return data
    const message = event.message
    if (event.event === 'message.updated') {
      return {
        ...data,
        pages: data.pages.map((p) => ({ ...p, results: p.results.map((m) => (m.id === message.id ? message : m)) })),
      }
    }
    if (data.pages.some((p) => p.results.some((m) => m.id === message.id))) return data
    const [first, ...rest] = data.pages
    return { ...data, pages: [{ ...first, results: [message, ...first.results] }, ...rest] }
  })
}

export function conversationTitle(c: Pick<Conversation, 'kind' | 'name' | 'other_person' | 'is_default' | 'channel_type'>, t: (k: string) => string) {
  if (c.kind === 'direct') return c.other_person?.full_name ?? ''
  if (c.is_default && c.channel_type === 'general') return t('chat.general')
  return c.name
}
