import { useInfiniteQuery } from '@tanstack/react-query'
import { ArrowLeft, AtSign, Hash, Lock, Search } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { EmptyState, ErrorState, FormField, SimpleSelect, UserAvatar } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { MENTIONS_KEY, conversationTitle, cursorOf, useConversations, type FoundMessage, type FoundPage } from '@/lib/chat'
import { useFormat } from '@/lib/format'
import { useUserOptions } from '@/lib/queries'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { cn } from '@/lib/utils'
import { MessageText } from './MessageBody'
import { BIDI_TEXT } from './text'

function PaneHeader({ icon: Icon, title, children }: { icon: typeof AtSign; title: string; children?: React.ReactNode }) {
  const { t } = useTranslation()
  return (
    <header className="border-b p-3">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon-sm" className="md:hidden" nativeButton={false} render={<Link to="/chat" />} aria-label={t('chat.back')}>
          <ArrowLeft className="size-4 rtl:rotate-180" />
        </Button>
        <Icon className="size-4 text-muted-foreground" />
        <h2 className="flex-1 text-base font-semibold">{title}</h2>
      </div>
      {children}
    </header>
  )
}

/** One found message: where it was said, who, when, the text (search words highlighted). Opens it in context. */
function FoundRow({ message: m, words }: { message: FoundMessage; words?: string[] }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const name = m.author?.full_name ?? t('chat.someone')
  return (
    <li>
      <Link
        to={`/chat/${m.conversation}?message=${m.id}`}
        className="flex gap-2.5 rounded-md px-3 py-2.5 hover:bg-muted focus-visible:bg-muted"
        aria-label={t('chat.openInContext', { name, where: m.conversation_title })}
      >
        <UserAvatar name={name} src={m.author?.avatar} className="size-8" />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1 font-medium text-foreground">
              {m.conversation_kind === 'channel' && (m.conversation_title.startsWith('#') ? <Hash className="size-3" /> : <Lock className="size-3" />)}
              <bdi>{m.conversation_title.replace(/^#/, '')}</bdi>
            </span>
            <bdi className="font-medium">{name}</bdi>
            <time dateTime={m.created_at}>
              <bdi>{fmt.dateTime(m.created_at)}</bdi>
            </time>
          </span>
          <span className={cn('mt-0.5 line-clamp-3 text-sm whitespace-pre-wrap', BIDI_TEXT)}>
            {m.body ? <MessageText body={m.body} words={words} links={false} /> : `📎 ${m.attachments.map((a) => a.original_name).join(', ')}`}
          </span>
        </span>
      </Link>
    </li>
  )
}

function FoundList({
  pages,
  loading,
  error,
  retry,
  hasMore,
  loadingMore,
  onMore,
  empty,
  words,
}: {
  pages: FoundPage[] | undefined
  loading: boolean
  error: boolean
  retry: () => void
  hasMore: boolean
  loadingMore: boolean
  onMore: () => void
  empty: React.ReactNode
  words?: string[]
}) {
  const { t } = useTranslation()
  const items = (pages ?? []).flatMap((p) => p.results)
  if (error) return <ErrorState onRetry={retry} />
  if (loading) {
    return (
      <div className="space-y-3 p-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-14" />
        ))}
      </div>
    )
  }
  if (!items.length) return <>{empty}</>
  return (
    <>
      <ol className="divide-y">
        {items.map((m) => (
          <FoundRow key={m.id} message={m} words={words} />
        ))}
      </ol>
      {hasMore && (
        <div className="p-3 text-center">
          <Button variant="outline" size="sm" onClick={onMore} disabled={loadingMore}>
            {t('chat.loadMore')}
          </Button>
        </div>
      )}
    </>
  )
}

/** Messages that mention me (by name, @channel or @here), newest first. */
export function MentionsPane({ className }: { className?: string }) {
  const { t } = useTranslation()
  const q = useInfiniteQuery({
    queryKey: [...MENTIONS_KEY, 'list'],
    queryFn: async ({ pageParam }) => (await api.get<FoundPage>('/chat/mentions/', { params: { cursor: pageParam } })).data,
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => cursorOf(last.next),
  })
  return (
    <section className={cn('flex min-h-0 flex-col', className)} aria-label={t('chat.mentions')}>
      <PaneHeader icon={AtSign} title={t('chat.mentions')} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <FoundList
          pages={q.data?.pages}
          loading={q.isLoading}
          error={q.isError}
          retry={() => void q.refetch()}
          hasMore={!!q.hasNextPage}
          loadingMore={q.isFetchingNextPage}
          onMore={() => void q.fetchNextPage()}
          empty={<EmptyState icon={AtSign} title={t('chat.noMentions')} hint={t('chat.noMentionsHint')} className="py-12" />}
        />
      </div>
    </section>
  )
}

/** Search messages in the conversations you can read, with filters. The URL keeps the search (shareable, Back works). */
export function SearchPane({ className }: { className?: string }) {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const [text, setText] = useState(params.get('q') ?? '')
  const q = useDebouncedValue(text.trim(), 300)
  const conversation = params.get('conversation') ?? ''
  const author = params.get('author') ?? ''
  const dateFrom = params.get('date_from') ?? ''
  const dateTo = params.get('date_to') ?? ''
  const { data: conversations } = useConversations()
  const { data: people } = useUserOptions()
  const setParam = (key: string, value: string) =>
    setParams((p) => {
      if (value) p.set(key, value)
      else p.delete(key)
      return p
    }, { replace: true })

  const filters = { q, conversation: conversation || undefined, author: author || undefined, date_from: dateFrom || undefined, date_to: dateTo || undefined }
  const results = useInfiniteQuery({
    queryKey: ['chat', 'search', filters],
    queryFn: async ({ pageParam }) => (await api.get<FoundPage>('/chat/search/', { params: { ...filters, cursor: pageParam } })).data,
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => cursorOf(last.next),
    enabled: q.length >= 2,
  })
  const words = results.data?.pages[0]?.terms

  return (
    <section className={cn('flex min-h-0 flex-col', className)} aria-label={t('chat.searchMessages')}>
      <PaneHeader icon={Search} title={t('chat.searchMessages')}>
        <div className="mt-3 grid gap-2">
          <label className="flex items-center gap-2 rounded-md border bg-background px-2">
            <Search className="size-4 text-muted-foreground" />
            <input
              autoFocus
              type="search"
              value={text}
              onChange={(e) => {
                setText(e.target.value)
                setParam('q', e.target.value.trim())
              }}
              placeholder={t('chat.searchPlaceholder')}
              aria-label={t('chat.searchMessages')}
              dir="auto"
              className="h-9 min-w-0 flex-1 bg-transparent text-sm outline-none"
            />
          </label>
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
            <FormField id="search-in" label={t('chat.searchIn')}>
              <SimpleSelect
                id="search-in"
                value={conversation}
                onChange={(v) => setParam('conversation', v)}
                options={[
                  { value: '', label: t('chat.everywhere') },
                  ...(conversations ?? []).map((c) => ({ value: String(c.id), label: conversationTitle(c, t) })),
                ]}
              />
            </FormField>
            <FormField id="search-from" label={t('chat.searchFrom')}>
              <SimpleSelect
                id="search-from"
                value={author}
                onChange={(v) => setParam('author', v)}
                options={[{ value: '', label: t('chat.anyone') }, ...(people ?? []).map((u) => ({ value: String(u.id), label: u.full_name }))]}
              />
            </FormField>
            <FormField id="search-after" label={t('chat.searchAfter')}>
              <Input id="search-after" type="date" value={dateFrom} max={dateTo || undefined} onChange={(e) => setParam('date_from', e.target.value)} />
            </FormField>
            <FormField id="search-before" label={t('chat.searchBefore')}>
              <Input id="search-before" type="date" value={dateTo} min={dateFrom || undefined} onChange={(e) => setParam('date_to', e.target.value)} />
            </FormField>
          </div>
        </div>
      </PaneHeader>
      <div className="min-h-0 flex-1 overflow-y-auto" aria-live="polite">
        {q.length < 2 ? (
          <EmptyState icon={Search} title={t('chat.searchStart')} hint={t('chat.searchHint')} className="py-12" />
        ) : (
          <FoundList
            pages={results.data?.pages}
            loading={results.isLoading}
            error={results.isError}
            retry={() => void results.refetch()}
            hasMore={!!results.hasNextPage}
            loadingMore={results.isFetchingNextPage}
            onMore={() => void results.fetchNextPage()}
            words={words}
            empty={<EmptyState icon={Search} title={t('chat.noResults')} hint={t('chat.noResultsHint')} className="py-12" />}
          />
        )}
      </div>
    </section>
  )
}
