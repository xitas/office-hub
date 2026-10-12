import { useQuery, type InfiniteData, type QueryClient } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'
import { api } from './api'
import { useMe } from './auth'

export interface ChatPerson {
  id: number
  full_name: string
  avatar: string | null
}

export interface ChatAttachment {
  id: number
  original_name: string
  size: number
  content_type: string
  kind: 'image' | 'pdf' | 'office' | 'text' | 'zip'
  download_url: string
  thumbnail_url: string | null
}

export interface ChatReaction {
  emoji: string
  count: number
  users: { id: number; full_name: string }[]
}

export interface ChatMessage {
  id: number
  conversation: number
  author: ChatPerson | null
  body: string
  reply_to: number | null
  reply: { id: number; author: ChatPerson | null; body: string; deleted: boolean } | null
  reactions: ChatReaction[]
  attachments: ChatAttachment[]
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
  muted: boolean
  last_read_id: number
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

/** Reactions anyone can add (the same fixed set as the server). */
export const REACTIONS = ['👍', '❤️', '😂', '🎉', '😮', '🙏'] as const
export const MAX_MESSAGE = 4000
export const MAX_FILES = 5

/** Live events pushed over the shared WebSocket (only to members). */
export type ChatEvent =
  | { type: 'chat'; event: 'message.new' | 'message.updated'; conversation: number; message: ChatMessage; unread: number }
  | { type: 'chat'; event: 'read'; conversation: number; unread: number }
  | { type: 'chat'; event: 'conversation.changed'; conversation: number }
  | { type: 'chat'; event: 'typing'; conversation: number; user: { id: number; full_name: string } }
  | { type: 'chat'; event: 'presence'; user: number; online: boolean }

export const CONVERSATIONS_KEY = ['chat', 'conversations'] as const
export const CHAT_UNREAD_KEY = ['chat', 'unread'] as const
export const PRESENCE_KEY = ['chat', 'presence'] as const
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

/** Colleagues online now. Live events keep it current; a refetch every minute covers connections that vanished. */
export function useOnline() {
  const me = useMe()
  const { data } = useQuery({
    queryKey: PRESENCE_KEY,
    queryFn: async () => new Set((await api.get<{ online: number[] }>('/chat/conversations/presence/')).data.online),
    enabled: me.permissions.includes('chat.view'),
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
  return data ?? new Set<number>()
}

// ---------------------------------------------------------------- typing ("Sana is typing…")

const TYPING_SHOWN_MS = 5000
type Typist = { id: number; full_name: string; until: number }
let typing: Record<number, Typist[]> = {}
const typingListeners = new Set<() => void>()
const emitTyping = () => typingListeners.forEach((fn) => fn())

function addTypist(conversation: number, user: { id: number; full_name: string }) {
  const now = Date.now()
  const others = (typing[conversation] ?? []).filter((t) => t.id !== user.id && t.until > now)
  typing = { ...typing, [conversation]: [...others, { ...user, until: now + TYPING_SHOWN_MS }] }
  emitTyping()
  window.setTimeout(() => {
    const left = (typing[conversation] ?? []).filter((t) => t.until > Date.now())
    typing = { ...typing, [conversation]: left }
    emitTyping()
  }, TYPING_SHOWN_MS + 50)
}

function removeTypist(conversation: number, userId: number) {
  if (!typing[conversation]?.some((t) => t.id === userId)) return
  typing = { ...typing, [conversation]: typing[conversation].filter((t) => t.id !== userId) }
  emitTyping()
}

const EMPTY: Typist[] = []
/** People typing in a conversation right now (cleared after 5 s without a new signal, or when their message arrives). */
export function useTyping(conversation: number) {
  return useSyncExternalStore(
    (fn) => {
      typingListeners.add(fn)
      return () => typingListeners.delete(fn)
    },
    () => typing[conversation] ?? EMPTY,
  )
}

// ---------------------------------------------------------------- drafts (kept per conversation while switching)

export interface Draft {
  text: string
  /** People picked from the @ suggestions (their "@Full Name" becomes a mention token when sent). */
  mentions: ChatPerson[]
}
const drafts = new Map<number, Draft>()
export const getDraft = (conversation: number): Draft => drafts.get(conversation) ?? { text: '', mentions: [] }
export const setDraft = (conversation: number, draft: Draft) => {
  if (draft.text) drafts.set(conversation, draft)
  else drafts.delete(conversation)
}

// ---------------------------------------------------------------- mentions, search

/** A message found by search or in "Mentions", with where it was said. */
export interface FoundMessage extends ChatMessage {
  conversation_title: string
  conversation_kind: 'channel' | 'direct'
}

export interface FoundPage {
  next: string | null
  previous: string | null
  results: FoundMessage[]
  /** Mentions: how many are still unread. */
  unread?: number
  /** Search: the words to highlight. */
  terms?: string[]
}

export const MENTIONS_KEY = ['chat', 'mentions'] as const

/** Mentions of me not read yet (for the "Mentions" entry and the dashboard). */
export function useUnreadMentions() {
  const me = useMe()
  const { data } = useQuery({
    queryKey: [...MENTIONS_KEY, 'unread'],
    queryFn: async () => (await api.get<FoundPage>('/chat/mentions/')).data.unread ?? 0,
    enabled: me.permissions.includes('chat.view'),
    staleTime: 30_000,
  })
  return data ?? 0
}

/** People to suggest after "@" (and whether @channel / @here may be offered). */
export interface MentionSuggestions {
  people: ChatPerson[]
  can_broadcast: boolean
}

/** Large channels ask before @channel / @here notifies everyone (same number as the server). */
export const BROADCAST_CONFIRM_ABOVE = 10
export const BROADCAST_RE = /(?<![\w@[])@(channel|here)\b/

/** The `cursor` value from a pagination link (links point at the API host, so only the cursor is reused). */
export function cursorOf(link: string | null) {
  if (!link) return undefined
  return new URL(link, window.location.origin).searchParams.get('cursor') ?? undefined
}

/** A message opened "in context" (from search or Mentions): the messages around it. */
export interface AroundPage {
  results: ChatMessage[]
  has_newer: boolean
  has_older: boolean
}
export const aroundKey = (conversation: number, message: number) => ['chat', 'around', conversation, message] as const

/** Replace one message wherever it is cached (history and "in context" views): edits, reactions, deletions. */
export function replaceMessage(queryClient: QueryClient, message: ChatMessage) {
  const swap = (m: ChatMessage) => (m.id === message.id ? message : m)
  queryClient.setQueryData<InfiniteData<MessagePage>>(messagesKey(message.conversation), (data) =>
    data && { ...data, pages: data.pages.map((p) => ({ ...p, results: p.results.map(swap) })) },
  )
  queryClient.setQueriesData<AroundPage>({ queryKey: ['chat', 'around', message.conversation] }, (data) =>
    data && { ...data, results: data.results.map(swap) },
  )
}

/** Add a new message to the cached history (ignored if already there, e.g. our own send and its live echo). */
export function addMessage(queryClient: QueryClient, message: ChatMessage) {
  queryClient.setQueryData<InfiniteData<MessagePage>>(messagesKey(message.conversation), (data) => {
    if (!data || data.pages.some((p) => p.results.some((m) => m.id === message.id))) return data
    const [first, ...rest] = data.pages
    return { ...data, pages: [{ ...first, results: [message, ...first.results] }, ...rest] }
  })
}

/** Mention tokens written by the picker: @[Full Name](user:12). */
export const MENTION_TOKEN = /@\[([^\]\n]{1,150})\]\(user:(\d+)\)/g

/** The text as people read it: mention tokens become "@Full Name". */
export function plainText(body: string) {
  return body.replace(MENTION_TOKEN, (_m, name: string) => `@${name}`)
}

export function previewOf(m: Pick<ChatMessage, 'body' | 'attachments'>) {
  if (m.body) return plainText(m.body).slice(0, 120)
  return m.attachments.length ? `📎 ${m.attachments.map((a) => a.original_name).join(', ')}`.slice(0, 120) : ''
}

/** Apply a live chat event to the cached conversation list, unread badge, presence, typing and open history. */
export function applyChatEvent(queryClient: QueryClient, event: ChatEvent) {
  if (event.event === 'presence') {
    queryClient.setQueryData<Set<number>>(PRESENCE_KEY, (old) => {
      const next = new Set(old)
      if (event.online) next.add(event.user)
      else next.delete(event.user)
      return next
    })
    return
  }
  if (event.event === 'typing') {
    addTypist(event.conversation, event.user)
    return
  }
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
          updated.last_message = { id: m.id, author: m.author, body: previewOf(m), deleted: m.deleted, created_at: m.created_at }
          updated.last_message_at = m.created_at
        } else if (event.event === 'message.updated' && c.last_message?.id === event.message.id) {
          updated.last_message = { ...c.last_message, body: previewOf(event.message), deleted: event.message.deleted }
        }
        return updated
      })
      .sort((a, b) => (b.last_message_at ?? '').localeCompare(a.last_message_at ?? ''))
  })
  if (!known) void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_KEY })
  void queryClient.invalidateQueries({ queryKey: CHAT_UNREAD_KEY })

  if (event.event === 'read') return
  if (event.event === 'message.updated') {
    replaceMessage(queryClient, event.message)
  } else {
    if (event.message.author) removeTypist(event.conversation, event.message.author.id)
    addMessage(queryClient, event.message)
    if (BROADCAST_RE.test(event.message.body) || event.message.body.includes('](user:')) {
      void queryClient.invalidateQueries({ queryKey: MENTIONS_KEY }) // it may mention me
    }
  }
}

export function conversationTitle(c: Pick<Conversation, 'kind' | 'name' | 'other_person' | 'is_default' | 'channel_type'>, t: (k: string) => string) {
  if (c.kind === 'direct') return c.other_person?.full_name ?? ''
  if (c.is_default && c.channel_type === 'general') return t('chat.general')
  return c.name
}
