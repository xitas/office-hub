import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { BellRing, History, MapPin, MoreHorizontal, Pencil, Trash2, UsersRound } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, SimpleSelect } from '@/components/common'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { api, apiError } from '@/lib/api'
import { useConfirm } from '@/lib/confirm'
import { ALL } from '@/lib/contacts'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import {
  KIND_ICONS,
  KIND_STYLES,
  TIMELINE_FILTERS,
  type CallDetails,
  type CreatedDetails,
  useAddEntry,
  type EntryInput,
  type MeetingDetails,
  type StatusDetails,
  type TimelineItem,
  type TimelineTarget,
} from '@/lib/timeline'
import type { Paginated } from '@/lib/types'
import { cn } from '@/lib/utils'
import { EntryForm } from './EntryForm'

/** Activity on a contact or company: logged notes/calls/meetings plus automatic entries, newest first.
 *  On a company it also lists entries from its contacts (marked with the contact's name). */
export function Timeline({ target }: { target: TimelineTarget }) {
  const { t } = useTranslation()
  const canAdd = usePermission('contacts.create')
  const [filter, setFilter] = useState(ALL)
  const add = useAddEntry()
  const isCompany = 'company' in target

  const query = useInfiniteQuery({
    queryKey: ['timeline', target, filter],
    queryFn: async ({ pageParam }) =>
      (
        await api.get<Paginated<TimelineItem>>('/timeline/', {
          params: { ...target, page: pageParam, ...(filter !== ALL && { type: filter }) },
        })
      ).data,
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (last.next ? pages.length + 1 : undefined),
  })
  const items = query.data?.pages.flatMap((p) => p.results) ?? []

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle>{t('timeline.title')}</CardTitle>
        <SimpleSelect
          className="w-auto min-w-40"
          value={filter}
          onChange={setFilter}
          options={[
            { value: ALL, label: t('timeline.allTypes') },
            ...TIMELINE_FILTERS.map((k) => ({ value: k, label: t(`timeline.filters.${k}`) })),
          ]}
        />
      </CardHeader>
      <CardContent className="grid gap-4">
        {canAdd && (
          <>
            <div className="rounded-lg border bg-muted/30 p-3">
              <EntryForm idPrefix="timeline-add" onSubmit={(input) => add.mutateAsync({ ...input, ...target })} />
            </div>
            <Separator />
          </>
        )}
        {query.isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        ) : query.isError ? (
          <ErrorState onRetry={() => void query.refetch()} />
        ) : !items.length ? (
          <EmptyState icon={History} title={t('timeline.empty')} hint={filter === ALL ? t('timeline.emptyHint') : undefined} />
        ) : (
          <ol className="relative">
            {items.map((item, i) => (
              <TimelineRow key={item.id} item={item} showContact={isCompany} last={i === items.length - 1} />
            ))}
          </ol>
        )}
        {query.hasNextPage && (
          <Button variant="outline" className="justify-self-center" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
            {query.isFetchingNextPage ? t('common.loading') : t('timeline.loadMore')}
          </Button>
        )}
      </CardContent>
    </Card>
  )
}

function TimelineRow({ item, showContact, last }: { item: TimelineItem; showContact: boolean; last: boolean }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const confirm = useConfirm()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const Icon = KIND_ICONS[item.kind] ?? History
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['timeline'] })

  const update = useMutation({
    mutationFn: async (input: Partial<EntryInput>) => (await api.patch(`/timeline/${item.entry_id}/`, input)).data,
    onSuccess: () => {
      refresh()
      setEditing(false)
      toast.success(t('common.saved'))
    },
  })
  const remove = useMutation({
    mutationFn: () => api.delete(`/timeline/${item.entry_id}/`),
    onSuccess: () => {
      refresh()
      toast.success(t('common.deleted'))
    },
    onError: (err) => toast.error(apiError(err).message),
  })

  const askDelete = async () => {
    const ok = await confirm({
      title: t('timeline.deleteTitle'),
      description: t('timeline.deleteHint'),
      confirmLabel: t('common.delete'),
      destructive: true,
    })
    if (ok) remove.mutate()
  }

  return (
    <li className="relative flex gap-3 pb-5 last:pb-0">
      {!last && <span aria-hidden className="absolute start-4 top-9 bottom-0 w-px -translate-x-1/2 bg-border rtl:translate-x-1/2" />}
      <span className={cn('z-10 flex size-8 shrink-0 items-center justify-center rounded-full', KIND_STYLES[item.kind] ?? KIND_STYLES.status)}>
        <Icon className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1 text-sm">
            <Headline item={item} />
            {showContact && item.contact && (
              <>
                {' · '}
                <Link to={`/contacts/${item.contact.id}`} className="text-primary hover:underline">
                  <bdi>{item.contact.name}</bdi>
                </Link>
              </>
            )}
            <p className="text-xs text-muted-foreground">
              <time dateTime={item.occurred_at} title={fmt.dateTime(item.occurred_at)}>
                {fmt.relative(item.occurred_at)}
              </time>
              {item.created_by_name && (
                <>
                  {' · '}
                  <bdi>{item.created_by_name}</bdi>
                </>
              )}
            </p>
          </div>
          {item.editable && !editing && (
            <DropdownMenu>
              <DropdownMenuTrigger render={<Button variant="ghost" size="icon" className="-me-2 size-8" aria-label={t('common.actions')} />}>
                <MoreHorizontal className="size-4" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => setEditing(true)}>
                  <Pencil className="size-4" />
                  {t('common.edit')}
                </DropdownMenuItem>
                <DropdownMenuItem variant="destructive" onClick={() => void askDelete()}>
                  <Trash2 className="size-4" />
                  {t('common.delete')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>

        {editing ? (
          <div className="mt-2 rounded-lg border p-3">
            <EntryForm
              entry={item}
              idPrefix={`edit-${item.id.replace(':', '-')}`}
              autoFocus
              onSubmit={(input) => update.mutateAsync(input)}
              onCancel={() => setEditing(false)}
            />
          </div>
        ) : (
          <Body item={item} />
        )}
      </div>
    </li>
  )
}

function Headline({ item }: { item: TimelineItem }) {
  const { t } = useTranslation()
  if (item.kind === 'call') {
    const d = item.details as CallDetails
    return (
      <span className="font-medium">
        {t(`timeline.callTitle.${d.direction ?? 'out'}`)}
        {d.outcome && <span className="font-normal text-muted-foreground"> · {t(`timeline.outcomes.${d.outcome}`)}</span>}
        {d.duration_minutes != null && (
          <span className="font-normal text-muted-foreground"> · {t('timeline.minutes', { count: d.duration_minutes })}</span>
        )}
      </span>
    )
  }
  if (item.kind === 'status') {
    const d = item.details as unknown as StatusDetails
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5 font-medium">
        {t('timeline.statusChanged')}
        <StatusBadge status={d.from} />
        <span aria-hidden className="rtl:rotate-180">→</span>
        <StatusBadge status={d.to} />
      </span>
    )
  }
  if (item.kind === 'created') {
    const d = item.details as unknown as CreatedDetails
    return (
      <span className="font-medium">
        {t(d.record === 'company' ? 'timeline.companyCreated' : 'timeline.contactCreated')}
        {d.status && <StatusBadge status={d.status} className="ms-1.5" />}
      </span>
    )
  }
  const known = ['note', 'meeting'].includes(item.kind)
  return <span className="font-medium">{known ? t(`timeline.kinds.${item.kind}`) : item.kind}</span>
}

function Body({ item }: { item: TimelineItem }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const meeting = item.kind === 'meeting' ? (item.details as MeetingDetails) : null
  const hasExtras = !!(meeting?.location || meeting?.attendees || item.follow_up_on)
  if (!item.summary && !hasExtras) return null
  return (
    <div className="mt-1.5 grid gap-1.5">
      {item.summary && (
        <p dir="auto" className={cn('text-sm whitespace-pre-wrap break-words', item.kind === 'status' && 'text-muted-foreground italic')}>
          {item.summary}
        </p>
      )}
      {hasExtras && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {meeting?.location && (
            <span className="inline-flex items-center gap-1">
              <MapPin className="size-3.5" />
              <bdi>{meeting.location}</bdi>
            </span>
          )}
          {meeting?.attendees && (
            <span className="inline-flex items-center gap-1">
              <UsersRound className="size-3.5" />
              <bdi>{meeting.attendees}</bdi>
            </span>
          )}
          {item.follow_up_on && (
            <Badge variant="outline" className="gap-1 font-normal">
              <BellRing className="size-3" />
              {t('timeline.followUpOn', { date: fmt.date(item.follow_up_on) })}
            </Badge>
          )}
        </div>
      )}
    </div>
  )
}
