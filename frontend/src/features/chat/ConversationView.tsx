import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ArrowDown, ArrowLeft, ArrowUp, Bell, BellOff, Upload, Users } from 'lucide-react'
import { Fragment, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { ErrorState, UserAvatar } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api, apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import {
  CHAT_UNREAD_KEY,
  CONVERSATIONS_KEY,
  conversationTitle,
  cursorOf,
  messagesKey,
  useOnline,
  useTyping,
  type ChatMessage,
  type Conversation,
  type MessagePage,
} from '@/lib/chat'
import { useFormat } from '@/lib/format'
import { cn } from '@/lib/utils'
import { setViewing } from '@/lib/ws'
import { ChannelIcon, PresenceDot } from './ChatPage'
import { Composer, type ComposerHandle } from './Composer'
import { MessageItem } from './MessageItem'
import { announce } from './text'

const MAX_JUMP_PAGES = 10 // how far back "jump to" loads older messages

export function ConversationView({ id, className }: { id: number; className?: string }) {
  const { t } = useTranslation()
  const me = useMe()
  const queryClient = useQueryClient()
  const online = useOnline()
  const composer = useRef<ComposerHandle>(null)
  const [replyTo, setReplyTo] = useState<ChatMessage | null>(null)
  const [dragging, setDragging] = useState(false)

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
  const c = conversation.data

  // This tab shows the conversation: no notifications for it while it's open and visible.
  useEffect(() => {
    setViewing(id)
    return () => setViewing(null)
  }, [id])

  // Where the reader had read up to when they opened it (the "unread" divider stays put while reading).
  const [readMark, setReadMark] = useState<number | null>(null)
  if (c && readMark === null) setReadMark(c.is_member ? c.last_read_id : Number.MAX_SAFE_INTEGER)

  const messages = (history.data?.pages ?? []).flatMap((p) => p.results).slice().reverse() // oldest first
  const newestId = messages.at(-1)?.id
  // Only what was unread on opening gets the divider; messages arriving while reading don't.
  const [openNewest, setOpenNewest] = useState<number | null>(null)
  if (openNewest === null && history.isSuccess) setOpenNewest(newestId ?? 0)
  const unread =
    readMark === null || openNewest === null
      ? []
      : messages.filter((m) => m.id > readMark && m.id <= openNewest && m.author?.id !== me.id)

  // Opening a conversation, or a new message arriving while it is open and visible, marks it read.
  useEffect(() => {
    if (!c?.is_member || newestId === undefined || document.visibilityState !== 'visible') return
    void api.post<{ unread: number }>(`/chat/conversations/${id}/read/`).then(() => {
      queryClient.setQueryData<Conversation[]>([...CONVERSATIONS_KEY, 'mine'], (list) =>
        list?.map((x) => (x.id === id ? { ...x, unread_count: 0 } : x)),
      )
      void queryClient.invalidateQueries({ queryKey: CHAT_UNREAD_KEY })
    })
  }, [c?.is_member, newestId, id, queryClient])

  /** Scroll to a message, loading older pages if it isn't loaded yet. */
  const jumpTo = async (messageId: number) => {
    for (let i = 0; i <= MAX_JUMP_PAGES; i++) {
      const el = document.getElementById(`message-${messageId}`)
      if (el) {
        el.scrollIntoView({ block: 'center', behavior: 'smooth' })
        el.focus({ preventScroll: true })
        el.classList.add('bg-primary/10')
        window.setTimeout(() => el.classList.remove('bg-primary/10'), 1600)
        return
      }
      const pages = queryClient.getQueryData<{ pages: MessagePage[] }>(messagesKey(id))?.pages
      if (!pages?.at(-1)?.next) break
      await history.fetchNextPage()
      await new Promise((r) => requestAnimationFrame(r))
    }
    toast.info(t('chat.tooOld'))
  }

  const mute = useMutation({
    mutationFn: async (muted: boolean) => (await api.post<Conversation>(`/chat/conversations/${id}/mute/`, { muted })).data,
    onSuccess: (updated) => {
      queryClient.setQueryData([...CONVERSATIONS_KEY, 'detail', id], updated)
      void queryClient.invalidateQueries({ queryKey: [...CONVERSATIONS_KEY, 'mine'] })
      void queryClient.invalidateQueries({ queryKey: CHAT_UNREAD_KEY })
      toast.success(updated.muted ? t('chat.mutedToast') : t('chat.unmutedToast'))
    },
    onError: (e) => toast.error(apiError(e).message),
  })

  if (conversation.isError) return <ErrorState onRetry={() => void conversation.refetch()} />
  if (!c) return <Skeleton className={cn('m-4 h-64', className)} />

  const title = conversationTitle(c, t)
  const otherOnline = c.kind === 'direct' && !!c.other_person && online.has(c.other_person.id)
  const acceptsFiles = c.can_post && !c.archived

  return (
    <section
      className={cn('relative flex min-h-0 flex-col', className)}
      aria-label={title}
      onDragOver={(e) => {
        if (!acceptsFiles || !e.dataTransfer.types.includes('Files')) return
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false)
      }}
      onDrop={(e) => {
        if (!acceptsFiles) return
        e.preventDefault()
        setDragging(false)
        composer.current?.addFiles(Array.from(e.dataTransfer.files))
      }}
    >
      <header className="flex items-center gap-2 border-b p-3">
        <Button variant="ghost" size="icon-sm" className="md:hidden" nativeButton={false} render={<Link to="/chat" />} aria-label={t('chat.back')}>
          <ArrowLeft className="size-4 rtl:rotate-180" />
        </Button>
        {c.kind === 'direct' ? (
          <span className="relative">
            <UserAvatar name={title} src={c.other_person?.avatar} className="size-8" />
            <PresenceDot online={otherOnline} />
          </span>
        ) : (
          <ChannelIcon conversation={c} />
        )}
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-base font-semibold">
            <bdi>{title}</bdi>
          </h2>
          <p className="truncate text-xs text-muted-foreground">
            {c.kind === 'channel' ? (
              <>
                <Users className="me-1 inline size-3" />
                {t('chat.members', { count: c.member_count })}
                {c.description && !c.is_default && <> · <bdi>{c.description}</bdi></>}
              </>
            ) : otherOnline ? (
              t('chat.online')
            ) : (
              t('chat.offline')
            )}
          </p>
        </div>
        {c.is_member && (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => mute.mutate(!c.muted)}
            disabled={mute.isPending}
            aria-pressed={c.muted}
            aria-label={c.muted ? t('chat.unmute') : t('chat.mute')}
            title={c.muted ? t('chat.unmute') : t('chat.mute')}
          >
            {c.muted ? <BellOff className="size-4 text-muted-foreground" /> : <Bell className="size-4" />}
          </Button>
        )}
      </header>

      <MessageList
        conversationId={id}
        messages={messages}
        loading={history.isLoading}
        hasOlder={!!history.hasNextPage}
        loadingOlder={history.isFetchingNextPage}
        onLoadOlder={() => void history.fetchNextPage()}
        canChange={c.can_post}
        firstUnreadId={unread[0]?.id}
        unreadCount={unread.length}
        onReply={setReplyTo}
        onJump={(mid) => void jumpTo(mid)}
      />

      <TypingLine conversationId={id} />

      {c.archived ? (
        <p className="flex items-center justify-center gap-2 border-t p-3 text-sm text-muted-foreground">
          <Archive className="size-4" />
          {t('chat.archived')}
        </p>
      ) : c.can_post ? (
        <Composer
          ref={composer}
          conversationId={id}
          placeholder={t('chat.writeTo', { name: title })}
          replyTo={replyTo}
          onCancelReply={() => setReplyTo(null)}
        />
      ) : (
        <JoinBar conversation={c} />
      )}

      {dragging && (
        <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center rounded-xl border-2 border-dashed border-primary bg-background/80">
          <p className="flex items-center gap-2 text-sm font-medium text-primary">
            <Upload className="size-4" />
            {t('chat.dropFiles')}
          </p>
        </div>
      )}
    </section>
  )
}

/** "Today", "Yesterday" or the date, in the office time zone. */
function useDays() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const zone = fmt.settings.timezone
  const key = (d: Date | string) =>
    new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(d))
  const label = (d: string, today: string, yesterday: string) => {
    const k = key(d)
    return k === today ? t('chat.today') : k === yesterday ? t('chat.yesterday') : fmt.date(d)
  }
  return { key, label }
}

function MessageList({
  conversationId,
  messages,
  loading,
  hasOlder,
  loadingOlder,
  onLoadOlder,
  canChange,
  firstUnreadId,
  unreadCount,
  onReply,
  onJump,
}: {
  conversationId: number
  messages: ChatMessage[]
  loading: boolean
  hasOlder: boolean
  loadingOlder: boolean
  onLoadOlder: () => void
  canChange: boolean
  firstUnreadId?: number
  unreadCount: number
  onReply: (m: ChatMessage) => void
  onJump: (id: number) => void
}) {
  const { t } = useTranslation()
  const me = useMe()
  const scroller = useRef<HTMLDivElement>(null)
  const followRef = useRef(true) // read by the scroll effect
  const opened = useRef(false)
  const prevNewest = useRef<number | undefined>(undefined)
  const [following, setFollowing] = useState(true) // the reader is at the bottom
  const [seenUpTo, setSeenUpTo] = useState(0) // newest message they had seen when they scrolled up
  const [dividerAbove, setDividerAbove] = useState(false)
  const newest = messages.at(-1)
  // The newest message when the history first loaded: only later ones are "new" (announced, counted).
  const [openNewest, setOpenNewest] = useState<number | null>(null)
  if (openNewest === null && !loading && newest) setOpenNewest(newest.id)
  const fresh = newest && openNewest !== null && newest.id > openNewest && newest.author?.id !== me.id ? newest : undefined
  const spoken = fresh ? announce(fresh, t) : ''
  const unseen = following ? 0 : messages.filter((m) => m.id > seenUpTo && m.author?.id !== me.id).length
  const days = useDays()
  // "Now", refreshed every 30 s: edit buttons disappear when the 15-minute window closes; day labels roll over.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [])
  const today = days.key(new Date(now))
  const yesterday = days.key(new Date(now - 86_400_000))

  const toBottom = (smooth = false) => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
    followRef.current = true
  }

  useLayoutEffect(() => {
    if (loading || !newest) return
    if (!opened.current) {
      // On open: show the first unread message (with the divider), or the newest one.
      opened.current = true
      prevNewest.current = newest.id
      const divider = scroller.current?.querySelector('[data-unread-divider]')
      if (divider) {
        divider.scrollIntoView({ block: 'start' })
        const el = scroller.current!
        followRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80 // everything fits: keep following
      } else {
        toBottom()
      }
      return
    }
    if (prevNewest.current !== undefined && newest.id <= prevNewest.current) return // older messages loaded above
    prevNewest.current = newest.id
    // A new message: follow it only if the reader was already at the bottom (or sent it); otherwise the button shows.
    if (newest.author?.id === me.id || followRef.current) toBottom()
  }, [loading, newest, me.id])

  // Images load after the text: stay pinned to the bottom while their height arrives.
  const list = useRef<HTMLOListElement>(null)
  useEffect(() => {
    const el = scroller.current
    const content = list.current
    if (!el || !content) return
    const observer = new ResizeObserver(() => {
      if (followRef.current) el.scrollTop = el.scrollHeight
    })
    observer.observe(content)
    return () => observer.disconnect()
  }, [loading])

  const onScroll = () => {
    const el = scroller.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    if (!atBottom && following && newest) setSeenUpTo(newest.id) // just left the bottom
    followRef.current = atBottom
    setFollowing(atBottom)
    const divider = el.querySelector<HTMLElement>('[data-unread-divider]')
    setDividerAbove(!!divider && divider.getBoundingClientRect().bottom < el.getBoundingClientRect().top)
  }

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      {firstUnreadId !== undefined && dividerAbove && (
        <button
          type="button"
          onClick={() => onJump(firstUnreadId)}
          className="absolute inset-x-0 top-0 z-10 flex items-center justify-center gap-1.5 bg-primary/90 py-1 text-xs font-medium text-primary-foreground"
        >
          <ArrowUp className="size-3.5" />
          {t('chat.jumpToUnread', { count: unreadCount })}
        </button>
      )}
      <div
        ref={scroller}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-y-auto px-3 py-3"
        role="region"
        aria-label={t('chat.messages')}
        tabIndex={0}
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
            <ol ref={list} className="space-y-1" id={`messages-${conversationId}`}>
              {messages.map((m, i) => {
                const prev = messages[i - 1]
                const newDay = !prev || days.key(prev.created_at) !== days.key(m.created_at)
                const unreadStart = m.id === firstUnreadId
                return (
                  <Fragment key={m.id}>
                    {newDay && (
                      <li role="separator" className="flex items-center gap-3 py-2 text-xs font-medium text-muted-foreground">
                        <span className="h-px flex-1 bg-border" />
                        {days.label(m.created_at, today, yesterday)}
                        <span className="h-px flex-1 bg-border" />
                      </li>
                    )}
                    {unreadStart && (
                      <li role="separator" data-unread-divider className="flex items-center gap-3 py-1 text-xs font-medium text-destructive">
                        <span className="h-px flex-1 bg-destructive/50" />
                        {t('chat.unreadDivider')}
                        <span className="h-px flex-1 bg-destructive/50" />
                      </li>
                    )}
                    <MessageItem
                      message={m}
                      grouped={!newDay && !unreadStart && sameSender(prev, m)}
                      canChange={canChange}
                      now={now}
                      onReply={onReply}
                      onJump={onJump}
                    />
                  </Fragment>
                )
              })}
            </ol>
          </>
        )}
      </div>
      {unseen > 0 && (
        <Button
          size="sm"
          className="absolute bottom-3 left-1/2 z-10 -translate-x-1/2 rounded-full shadow-md"
          onClick={() => toBottom(true)}
        >
          <ArrowDown className="size-4" />
          {t('chat.newMessages', { count: unseen })}
        </Button>
      )}
      {/* Screen readers hear new messages from others, politely, once each. */}
      <p className="sr-only" aria-live="polite" aria-atomic>
        {spoken}
      </p>
    </div>
  )
}

/** Consecutive messages by the same person within 5 minutes share one header. */
function sameSender(prev: ChatMessage | undefined, m: ChatMessage) {
  if (!prev || !prev.author || prev.author.id !== m.author?.id) return false
  return new Date(m.created_at).getTime() - new Date(prev.created_at).getTime() < 5 * 60_000
}

function TypingLine({ conversationId }: { conversationId: number }) {
  const { t } = useTranslation()
  const people = useTyping(conversationId)
  const names = people.map((p) => p.full_name.split(' ')[0])
  const text =
    names.length === 0
      ? ''
      : names.length === 1
        ? t('chat.typingOne', { name: names[0] })
        : names.length === 2
          ? t('chat.typingTwo', { a: names[0], b: names[1] })
          : t('chat.typingMany')
  return (
    <p className="h-5 truncate px-4 text-xs text-muted-foreground italic" aria-live="polite">
      {text}
    </p>
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
