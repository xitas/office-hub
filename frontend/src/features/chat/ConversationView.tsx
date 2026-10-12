import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ArrowLeft, Pencil, SendHorizontal, Trash2, Users } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { ErrorState, UserAvatar } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import {
  CHAT_UNREAD_KEY,
  CONVERSATIONS_KEY,
  conversationTitle,
  cursorOf,
  messagesKey,
  type ChatMessage,
  type Conversation,
  type MessagePage,
} from '@/lib/chat'
import { useConfirm } from '@/lib/confirm'
import { useFormat } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ChannelIcon } from './ChatPage'

export function ConversationView({ id, className }: { id: number; className?: string }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const conversation = useQuery({
    queryKey: [...CONVERSATIONS_KEY, 'detail', id],
    queryFn: async () => (await api.get<Conversation>(`/chat/conversations/${id}/`)).data,
  })
  const history = useInfiniteQuery({
    queryKey: messagesKey(id),
    queryFn: async ({ pageParam }) =>
      (await api.get<MessagePage>(`/chat/conversations/${id}/messages/`, { params: { cursor: pageParam } })).data,
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => cursorOf(last.next),
    enabled: conversation.isSuccess,
  })

  // Oldest first for display; pages arrive newest first.
  const messages = (history.data?.pages ?? []).flatMap((p) => p.results).slice().reverse()
  const newestId = messages.at(-1)?.id
  const c = conversation.data

  // Opening a conversation, or a new message arriving while it is open, marks it read.
  useEffect(() => {
    if (!c?.is_member || newestId === undefined || document.visibilityState !== 'visible') return
    void api.post<{ unread: number }>(`/chat/conversations/${id}/read/`).then(() => {
      queryClient.setQueryData<Conversation[]>([...CONVERSATIONS_KEY, 'mine'], (list) =>
        list?.map((x) => (x.id === id ? { ...x, unread_count: 0 } : x)),
      )
      void queryClient.invalidateQueries({ queryKey: CHAT_UNREAD_KEY })
    })
  }, [c?.is_member, newestId, id, queryClient])

  if (conversation.isError) return <ErrorState onRetry={() => void conversation.refetch()} />
  if (!c) return <Skeleton className={cn('m-4 h-64', className)} />

  const title = conversationTitle(c, t)
  return (
    <section className={cn('flex min-h-0 flex-col', className)} aria-label={title}>
      <header className="flex items-center gap-2 border-b p-3">
        <Button variant="ghost" size="icon-sm" className="md:hidden" nativeButton={false} render={<Link to="/chat" />} aria-label={t('chat.back')}>
          <ArrowLeft className="size-4 rtl:rotate-180" />
        </Button>
        {c.kind === 'direct' ? (
          <UserAvatar name={title} src={c.other_person?.avatar} className="size-8" />
        ) : (
          <ChannelIcon conversation={c} />
        )}
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-base font-semibold">
            <bdi>{title}</bdi>
          </h2>
          {c.kind === 'channel' && (
            <p className="truncate text-xs text-muted-foreground">
              <Users className="me-1 inline size-3" />
              {t('chat.members', { count: c.member_count })}
              {c.description && !c.is_default && <> · <bdi>{c.description}</bdi></>}
            </p>
          )}
        </div>
      </header>

      <MessageList
        messages={messages}
        loading={history.isLoading}
        hasOlder={!!history.hasNextPage}
        loadingOlder={history.isFetchingNextPage}
        onLoadOlder={() => void history.fetchNextPage()}
        canChange={c.can_post}
      />

      {c.archived ? (
        <p className="flex items-center justify-center gap-2 border-t p-3 text-sm text-muted-foreground">
          <Archive className="size-4" />
          {t('chat.archived')}
        </p>
      ) : c.can_post ? (
        <Composer conversationId={id} placeholder={t('chat.writeTo', { name: title })} />
      ) : (
        <JoinBar conversation={c} />
      )}
    </section>
  )
}

function MessageList({
  messages,
  loading,
  hasOlder,
  loadingOlder,
  onLoadOlder,
  canChange,
}: {
  messages: ChatMessage[]
  loading: boolean
  hasOlder: boolean
  loadingOlder: boolean
  onLoadOlder: () => void
  canChange: boolean
}) {
  const { t } = useTranslation()
  const scroller = useRef<HTMLDivElement>(null)
  // "Now", refreshed every 30 s: edit buttons disappear when the 15-minute window closes.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [])
  const newestId = messages.at(-1)?.id
  const atBottom = useRef(true)

  // Stay at the bottom as new messages arrive (unless the reader scrolled up to older ones).
  useLayoutEffect(() => {
    const el = scroller.current
    if (el && atBottom.current) el.scrollTop = el.scrollHeight
  }, [newestId])

  return (
    <div
      ref={scroller}
      onScroll={(e) => {
        const el = e.currentTarget
        atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
      }}
      className="min-h-0 flex-1 overflow-y-auto px-3 py-3"
      role="log"
      aria-live="polite"
      aria-label={t('chat.messages')}
    >
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      ) : (
        <>
          {hasOlder && (
            <div className="mb-3 text-center">
              <Button variant="outline" size="sm" onClick={onLoadOlder} disabled={loadingOlder}>
                {t('chat.loadOlder')}
              </Button>
            </div>
          )}
          {!messages.length && <p className="py-10 text-center text-sm text-muted-foreground">{t('chat.empty')}</p>}
          <ol className="space-y-1">
            {messages.map((m, i) => (
              <MessageRow key={m.id} message={m} grouped={sameSender(messages[i - 1], m)} canChange={canChange} now={now} />
            ))}
          </ol>
        </>
      )}
    </div>
  )
}

/** Consecutive messages by the same person within 5 minutes share one header. */
function sameSender(prev: ChatMessage | undefined, m: ChatMessage) {
  if (!prev || !prev.author || prev.author.id !== m.author?.id) return false
  return new Date(m.created_at).getTime() - new Date(prev.created_at).getTime() < 5 * 60_000
}

function MessageRow({ message: m, grouped, canChange, now }: { message: ChatMessage; grouped: boolean; canChange: boolean; now: number }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const me = useMe()
  const queryClient = useQueryClient()
  const confirm = useConfirm()
  const [editing, setEditing] = useState(false)
  const mine = m.author?.id === me.id
  const editable = mine && canChange && !m.deleted && !!m.editable_until && new Date(m.editable_until).getTime() > now
  const name = m.author?.full_name ?? t('chat.someone')

  const replace = (updated: ChatMessage) =>
    queryClient.setQueryData<{ pages: MessagePage[]; pageParams: unknown[] }>(messagesKey(m.conversation), (data) =>
      data && { ...data, pages: data.pages.map((p) => ({ ...p, results: p.results.map((x) => (x.id === updated.id ? updated : x)) })) },
    )
  const remove = useMutation({
    mutationFn: async () => api.delete(`/chat/messages/${m.id}/`),
    onSuccess: () => replace({ ...m, body: '', deleted: true, editable_until: null }),
    onError: (e) => toast.error(apiError(e).message),
  })

  return (
    <li id={`message-${m.id}`} className={cn('group flex gap-2.5 rounded-md px-1 py-0.5 hover:bg-muted/40', !grouped && 'mt-2')}>
      <div className="w-8 shrink-0">{!grouped && <UserAvatar name={name} src={m.author?.avatar} className="size-8" />}</div>
      <div className="min-w-0 flex-1">
        {!grouped && (
          <p className="flex items-baseline gap-2">
            <bdi className="text-sm font-semibold">{name}</bdi>
            <time dateTime={m.created_at} className="text-[11px] text-muted-foreground" title={fmt.dateTime(m.created_at)}>
              {fmt.relative(m.created_at)}
            </time>
          </p>
        )}
        {editing ? (
          <EditBox message={m} onDone={(updated) => {
            if (updated) replace(updated)
            setEditing(false)
          }} />
        ) : m.deleted ? (
          <p className="text-sm text-muted-foreground italic">{t('chat.deleted')}</p>
        ) : (
          <p className="text-sm break-words whitespace-pre-wrap [unicode-bidi:plaintext] ltr:text-left rtl:text-right">
            {m.body}
            {m.edited_at && <span className="ms-1.5 text-[11px] text-muted-foreground">({t('chat.edited')})</span>}
          </p>
        )}
      </div>
      {mine && !m.deleted && canChange && !editing && (
        <div className="flex shrink-0 items-start gap-0.5 opacity-100 transition-opacity md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100">
          {editable && (
            <Button variant="ghost" size="icon-xs" onClick={() => setEditing(true)} aria-label={t('chat.edit')} title={t('chat.edit')}>
              <Pencil className="size-3.5" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={t('chat.delete')}
            title={t('chat.delete')}
            onClick={async () => {
              if (await confirm({ title: t('chat.deleteConfirm'), confirmLabel: t('chat.delete'), destructive: true })) remove.mutate()
            }}
          >
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      )}
    </li>
  )
}

function EditBox({ message, onDone }: { message: ChatMessage; onDone: (updated?: ChatMessage) => void }) {
  const { t } = useTranslation()
  const [body, setBody] = useState(message.body)
  const save = useMutation({
    mutationFn: async () => (await api.patch<ChatMessage>(`/chat/messages/${message.id}/`, { body })).data,
    onSuccess: (updated) => onDone(updated),
    onError: (e) => toast.error(apiError(e).message),
  })
  return (
    <div className="mt-1 space-y-2">
      <Textarea
        value={body}
        dir="auto"
        autoFocus
        aria-label={t('chat.edit')}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onDone()
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            if (body.trim()) save.mutate()
          }
        }}
        className="min-h-16"
      />
      <div className="flex gap-2">
        <Button size="sm" onClick={() => save.mutate()} disabled={!body.trim() || save.isPending}>
          {t('common.save')}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onDone()}>
          {t('common.cancel')}
        </Button>
      </div>
    </div>
  )
}

function Composer({ conversationId, placeholder }: { conversationId: number; placeholder: string }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [body, setBody] = useState('')
  const send = useMutation({
    mutationFn: async (text: string) =>
      (await api.post<ChatMessage>(`/chat/conversations/${conversationId}/messages/`, { body: text })).data,
    onSuccess: (message) => {
      setBody('')
      // Shown at once; the live event for the same message is ignored as a duplicate.
      queryClient.setQueryData<{ pages: MessagePage[]; pageParams: unknown[] }>(messagesKey(conversationId), (data) => {
        if (!data || data.pages.some((p) => p.results.some((m) => m.id === message.id))) return data
        const [first, ...rest] = data.pages
        return { ...data, pages: [{ ...first, results: [message, ...first.results] }, ...rest] }
      })
      void queryClient.invalidateQueries({ queryKey: [...CONVERSATIONS_KEY, 'mine'] })
    },
    onError: (e) => toast.error(apiError(e).message),
  })
  const submit = () => {
    if (body.trim() && !send.isPending) send.mutate(body)
  }
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <form
      className="flex items-end gap-2 border-t p-3"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <Textarea
        value={body}
        dir="auto"
        rows={1}
        maxLength={4000}
        placeholder={placeholder}
        aria-label={t('chat.message')}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={onKeyDown}
        className="max-h-40 min-h-10 resize-none"
      />
      <Button type="submit" size="icon" disabled={!body.trim() || send.isPending} aria-label={t('chat.send')} title={t('chat.send')}>
        <SendHorizontal className="size-4 rtl:rotate-180" />
      </Button>
    </form>
  )
}

function JoinBar({ conversation }: { conversation: Conversation }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const join = useMutation({
    mutationFn: async () => (await api.post<Conversation>(`/chat/conversations/${conversation.id}/join/`)).data,
    onSuccess: (updated) => {
      queryClient.setQueryData([...CONVERSATIONS_KEY, 'detail', conversation.id], updated)
      void queryClient.invalidateQueries({ queryKey: [...CONVERSATIONS_KEY, 'mine'] })
    },
    onError: (e) => toast.error(apiError(e).message),
  })
  return (
    <div className="flex flex-wrap items-center justify-center gap-3 border-t p-3 text-sm text-muted-foreground">
      {t('chat.notMember')}
      {!conversation.is_private && (
        <Button size="sm" onClick={() => join.mutate()} disabled={join.isPending}>
          {t('chat.join')}
        </Button>
      )}
    </div>
  )
}
