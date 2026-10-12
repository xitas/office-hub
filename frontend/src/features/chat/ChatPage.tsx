import { AtSign, BellOff, Hash, Lock, MessageSquarePlus, MessagesSquare, Plus, Search, TextSearch } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, useLocation, useNavigate, useParams } from 'react-router-dom'
import { EmptyState, ErrorState, UserAvatar } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { conversationTitle, useConversations, useOnline, useUnreadMentions, type Conversation } from '@/lib/chat'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { useIsPhone } from '@/lib/useIsPhone'
import { cn } from '@/lib/utils'
import { BrowseChannelsDialog, NewChannelDialog, NewMessageDialog } from './ChatDialogs'
import { ConversationView } from './ConversationView'
import { MentionsPane, SearchPane } from './FoundViews'

/** Chat: conversation list on the left, the open conversation on the right (one at a time on phones). */
export function ChatPage() {
  const { t } = useTranslation()
  const { id } = useParams()
  const { pathname } = useLocation()
  const isPhone = useIsPhone()
  const pane = pathname.startsWith('/chat/mentions') ? 'mentions' : pathname.startsWith('/chat/search') ? 'search' : null
  const openId = id ? Number(id) : null
  const showList = !isPhone || (openId === null && pane === null)
  const showConversation = !isPhone || openId !== null || pane !== null

  return (
    <div className="-mt-2 flex h-[calc(100dvh-12rem)] min-h-[26rem] overflow-hidden rounded-xl border bg-card shadow-sm md:h-[calc(100dvh-7.5rem)]">
      <h1 className="sr-only">{t('chat.title')}</h1>
      {showList && <ConversationList openId={openId} className={cn('w-full md:w-80 md:shrink-0 md:border-e')} />}
      {showConversation &&
        (pane === 'mentions' ? (
          <MentionsPane className="min-w-0 flex-1" />
        ) : pane === 'search' ? (
          <SearchPane className="min-w-0 flex-1" />
        ) : openId ? (
          <ConversationView key={openId} id={openId} className="min-w-0 flex-1" />
        ) : (
          <div className="hidden flex-1 items-center justify-center md:flex">
            <EmptyState icon={MessagesSquare} title={t('chat.pickTitle')} hint={t('chat.pickHint')} />
          </div>
        ))}
    </div>
  )
}

function ConversationList({ openId, className }: { openId: number | null; className?: string }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const canCreateChannel = usePermission('chat.manage_channels')
  const { data, isLoading, isError, refetch } = useConversations()
  const [filter, setFilter] = useState('')
  const [dialog, setDialog] = useState<'dm' | 'browse' | 'channel' | null>(null)
  const mentions = useUnreadMentions()

  const match = (c: Conversation) => conversationTitle(c, t).toLowerCase().includes(filter.trim().toLowerCase())
  const channels = (data ?? []).filter((c) => c.kind === 'channel' && match(c))
  const directs = (data ?? []).filter((c) => c.kind === 'direct' && match(c))
  const opened = (c: Conversation) => {
    setDialog(null)
    navigate(`/chat/${c.id}`)
  }

  return (
    <aside className={cn('flex min-h-0 flex-col', className)} aria-label={t('chat.conversations')}>
      <div className="flex items-center gap-1 border-b p-3">
        <h2 className="flex-1 text-base font-semibold">{t('chat.title')}</h2>
        <Button size="icon-sm" variant="ghost" onClick={() => setDialog('browse')} aria-label={t('chat.browse')} title={t('chat.browse')}>
          <Hash className="size-4" />
        </Button>
        {canCreateChannel && (
          <Button size="icon-sm" variant="ghost" onClick={() => setDialog('channel')} aria-label={t('chat.newChannel')} title={t('chat.newChannel')}>
            <Plus className="size-4" />
          </Button>
        )}
        <Button size="icon-sm" variant="ghost" onClick={() => setDialog('dm')} aria-label={t('chat.newMessage')} title={t('chat.newMessage')}>
          <MessageSquarePlus className="size-4" />
        </Button>
      </div>
      <div className="border-b p-2">
        <label className="flex items-center gap-2 rounded-md border bg-background px-2">
          <Search className="size-4 text-muted-foreground" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t('chat.filter')}
            aria-label={t('chat.filter')}
            className="h-8 min-w-0 flex-1 bg-transparent text-sm outline-none"
          />
        </label>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto py-2">
        <ul className="mb-3">
          <ToolRow to="/chat/mentions" icon={AtSign} label={t('chat.mentions')} count={mentions} />
          <ToolRow to="/chat/search" icon={TextSearch} label={t('chat.searchMessages')} />
        </ul>
        {isError ? (
          <ErrorState onRetry={() => void refetch()} />
        ) : isLoading ? (
          <div className="space-y-2 px-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : (
          <>
            <Section title={t('chat.channels')}>
              {channels.map((c) => (
                <ConversationRow key={c.id} conversation={c} active={c.id === openId} />
              ))}
            </Section>
            <Section title={t('chat.directMessages')}>
              {directs.map((c) => (
                <ConversationRow key={c.id} conversation={c} active={c.id === openId} />
              ))}
              {!directs.length && !filter && (
                <li className="px-4 py-2 text-xs text-muted-foreground">{t('chat.noDirect')}</li>
              )}
            </Section>
          </>
        )}
      </div>
      {dialog === 'dm' && <NewMessageDialog onClose={() => setDialog(null)} onOpened={opened} />}
      {dialog === 'browse' && <BrowseChannelsDialog onClose={() => setDialog(null)} onOpened={opened} />}
      {dialog === 'channel' && <NewChannelDialog onClose={() => setDialog(null)} onOpened={opened} />}
    </aside>
  )
}

function ToolRow({ to, icon: Icon, label, count = 0 }: { to: string; icon: typeof AtSign; label: string; count?: number }) {
  const { t } = useTranslation()
  return (
    <li>
      <NavLink
        to={to}
        className={({ isActive }) =>
          cn('mx-2 flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm hover:bg-muted', isActive && 'bg-primary/10 font-medium hover:bg-primary/10')
        }
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted">
          <Icon className="size-4 text-muted-foreground" />
        </span>
        <span className="flex-1 truncate">{label}</span>
        {count > 0 && (
          <span className="min-w-5 rounded-full bg-amber-500 px-1.5 text-center text-[11px] leading-5 text-white font-latin">
            <span className="sr-only">{t('chat.unreadMentions', { count })}</span>
            <span aria-hidden>{count > 99 ? '99+' : count}</span>
          </span>
        )}
      </NavLink>
    </li>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-3">
      <h3 className="px-4 pb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h3>
      <ul>{children}</ul>
    </section>
  )
}

/** Green dot on an avatar when the colleague has the app open (announced as "online" to screen readers). */
export function PresenceDot({ online }: { online: boolean }) {
  const { t } = useTranslation()
  if (!online) return null
  return (
    <span className="absolute -end-0.5 -bottom-0.5 size-3 rounded-full border-2 border-card bg-success" role="img" aria-label={t('chat.online')} />
  )
}

export function ChannelIcon({ conversation, className }: { conversation: Pick<Conversation, 'is_private'>; className?: string }) {
  const Icon = conversation.is_private ? Lock : Hash
  return <Icon className={cn('size-4 shrink-0 text-muted-foreground', className)} />
}

function ConversationRow({ conversation: c, active }: { conversation: Conversation; active: boolean }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const online = useOnline()
  const title = conversationTitle(c, t)
  const preview = c.last_message
    ? c.last_message.deleted
      ? t('chat.deleted')
      : `${c.kind === 'channel' && c.last_message.author ? `${c.last_message.author.full_name.split(' ')[0]}: ` : ''}${c.last_message.body}`
    : t('chat.noMessages')
  const unread = c.unread_count > 0
  return (
    <li>
      <Link
        to={`/chat/${c.id}`}
        aria-current={active ? 'page' : undefined}
        className={cn(
          'mx-2 flex items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-muted',
          active && 'bg-primary/10 hover:bg-primary/10',
        )}
      >
        {c.kind === 'direct' ? (
          <span className="relative shrink-0">
            <UserAvatar name={title} src={c.other_person?.avatar} className="size-8" />
            <PresenceDot online={!!c.other_person && online.has(c.other_person.id)} />
          </span>
        ) : (
          <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted">
            <ChannelIcon conversation={c} />
          </span>
        )}
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <bdi className={cn('min-w-0 flex-1 truncate text-sm', unread && !c.muted && 'font-semibold')}>{title}</bdi>
            {c.muted && <BellOff className="size-3 shrink-0 text-muted-foreground" aria-label={t('chat.muted')} />}
            {c.last_message_at && <span className="shrink-0 text-[11px] text-muted-foreground">{fmt.relative(c.last_message_at)}</span>}
          </span>
          <span className="flex items-center gap-2">
            <span className={cn('min-w-0 flex-1 truncate [unicode-bidi:plaintext] ltr:text-left rtl:text-right text-xs text-muted-foreground', unread && 'text-foreground')}>
              {preview}
            </span>
            {unread && (
              <span className={cn('min-w-5 shrink-0 rounded-full px-1.5', c.muted ? 'bg-muted-foreground/30 text-foreground' : 'bg-primary text-primary-foreground')}>
                <span className="sr-only">{t('chat.unreadCount', { count: c.unread_count })}</span>
                <span aria-hidden className="block text-center text-[11px] leading-5 font-latin">{c.unread_count > 99 ? '99+' : c.unread_count}</span>
              </span>
            )}
          </span>
        </span>
      </Link>
    </li>
  )
}
