import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRightLeft, Building, Check, Clock, GripVertical } from 'lucide-react'
import { useState, type DragEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorState, UserAvatar } from '@/components/common'
import { TagList } from '@/components/common/TagList'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { CONTACT_STATUSES, filterParams, type ContactFilters } from '@/lib/contacts'
import { usePermission } from '@/lib/permissions'
import type { ContactStatus, PipelineCard, PipelineData } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useStatusChange } from '@/features/contacts/useStatusChange'

// Column accents use theme tokens (match the status badges) so they work in light and dark mode.
const ACCENT: Record<ContactStatus, string> = {
  new: 'bg-muted-foreground',
  contacted: 'bg-primary',
  in_discussion: 'bg-warning',
  won: 'bg-success',
  lost: 'bg-destructive',
}

const DAY = 86_400_000
const daysIn = (iso: string) => Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / DAY))

/** Moves a card between columns in cached board data (optimistic update). */
function moveCard(data: PipelineData, id: number, to: ContactStatus): PipelineData {
  let moved: PipelineCard | undefined
  const columns = data.columns.map((col) => {
    const card = col.cards.find((c) => c.id === id)
    if (!card) return col
    moved = card
    return { ...col, count: col.count - 1, cards: col.cards.filter((c) => c.id !== id) }
  })
  if (!moved) return data
  const card = { ...moved, status: to, status_changed_at: new Date().toISOString() }
  return {
    ...data,
    columns: columns.map((col) => (col.status === to ? { ...col, count: col.count + 1, cards: [card, ...col.cards] } : col)),
  }
}

export function PipelineBoard({ search, filters, onShowList }: { search: string; filters: ContactFilters; onShowList: (status: ContactStatus) => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const canMove = usePermission('contacts.edit')
  const [dragging, setDragging] = useState<PipelineCard | null>(null)
  const [over, setOver] = useState<ContactStatus | null>(null)
  const key = ['contacts', 'pipeline', { search, filters }]

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: key,
    queryFn: async () =>
      (await api.get<PipelineData>('/contacts/pipeline/', { params: { search: search || undefined, ...filterParams(filters, ['status']) } })).data,
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['contacts'] })
  }
  const { requestChange, dialog, pending } = useStatusChange({
    onStart: (id, to) => queryClient.setQueryData<PipelineData>(key, (old) => (old ? moveCard(old, id, to) : old)),
    onSuccess: refresh,
    onError: refresh,
  })

  if (isError) return <ErrorState onRetry={() => void refetch()} />
  if (isLoading || !data)
    return (
      <div className="flex gap-3 overflow-hidden">
        {CONTACT_STATUSES.map((s) => (
          <Skeleton key={s} className="h-96 w-72 shrink-0 rounded-xl lg:w-auto lg:flex-1" />
        ))}
      </div>
    )
  if (data.total === 0 && (search || Object.values(filters).some((v) => v !== 'all')))
    return <EmptyState title={t('common.noResults')} />

  const onDrop = (e: DragEvent, status: ContactStatus) => {
    e.preventDefault()
    setOver(null)
    if (dragging && dragging.status !== status) requestChange(dragging, status)
    setDragging(null)
  }

  return (
    <>
      {dialog}
      {/* Columns follow the reading direction, so in Urdu "New" is on the right. */}
      <div
        className="-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-3 md:mx-0 md:px-0 lg:grid lg:snap-none lg:grid-cols-5 lg:overflow-visible"
        role="list"
        aria-label={t('pipeline.boardLabel')}
      >
        {data.columns.map((col) => (
          <section
            key={col.status}
            role="listitem"
            aria-label={t('pipeline.columnLabel', { status: t(`contacts.statuses.${col.status}`), count: col.count })}
            onDragOver={(e) => {
              if (!dragging || dragging.status === col.status) return
              e.preventDefault()
              e.dataTransfer.dropEffect = 'move'
              setOver(col.status)
            }}
            onDragLeave={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(null)
            }}
            onDrop={(e) => onDrop(e, col.status)}
            className={cn(
              'flex w-[min(18rem,82vw)] shrink-0 snap-start flex-col rounded-xl border bg-muted/40 transition-colors lg:w-auto lg:min-w-0',
              over === col.status && 'border-primary bg-primary/5 ring-2 ring-primary/30',
            )}
          >
            <header className="flex items-center gap-2 px-3 pt-3 pb-2">
              <span className={cn('size-2.5 shrink-0 rounded-full', ACCENT[col.status])} aria-hidden />
              <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{t(`contacts.statuses.${col.status}`)}</h2>
              <Badge variant="secondary" className="font-latin tabular-nums">
                {col.count}
              </Badge>
            </header>
            <ul className="flex min-h-24 flex-1 flex-col gap-2 px-2 pb-2">
              {col.cards.map((card) => (
                <li key={card.id}>
                  <BoardCard
                    card={card}
                    canMove={canMove}
                    busy={pending === card.id}
                    dragging={dragging?.id === card.id}
                    onDragStart={() => setDragging(card)}
                    onDragEnd={() => {
                      setDragging(null)
                      setOver(null)
                    }}
                    onMove={(to) => requestChange(card, to)}
                  />
                </li>
              ))}
              {col.cards.length === 0 && (
                <li className="flex flex-1 items-center justify-center rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
                  {canMove ? t('pipeline.emptyColumnDrop') : t('pipeline.emptyColumn')}
                </li>
              )}
            </ul>
            {col.count > col.cards.length && (
              <Button variant="link" size="sm" className="mb-2 self-center" onClick={() => onShowList(col.status)}>
                {t('pipeline.showingOf', { shown: col.cards.length, count: col.count })}
              </Button>
            )}
          </section>
        ))}
      </div>
    </>
  )
}

function BoardCard({
  card,
  canMove,
  busy,
  dragging,
  onDragStart,
  onDragEnd,
  onMove,
}: {
  card: PipelineCard
  canMove: boolean
  busy: boolean
  dragging: boolean
  onDragStart: () => void
  onDragEnd: () => void
  onMove: (to: ContactStatus) => void
}) {
  const { t } = useTranslation()
  const days = daysIn(card.status_changed_at)

  return (
    <article
      draggable={canMove}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = 'move'
        e.dataTransfer.setData('text/plain', String(card.id))
        onDragStart()
      }}
      onDragEnd={onDragEnd}
      aria-busy={busy}
      className={cn(
        'group rounded-lg border bg-card p-3 text-sm shadow-card transition-opacity',
        canMove && 'cursor-grab active:cursor-grabbing',
        (dragging || busy) && 'opacity-50',
      )}
    >
      <div className="flex items-start gap-1">
        {canMove && <GripVertical className="mt-0.5 hidden size-4 shrink-0 text-muted-foreground/60 md:block" aria-hidden />}
        <div className="min-w-0 flex-1">
          <Link to={`/contacts/${card.id}`} className="block truncate font-medium hover:text-primary hover:underline" draggable={false}>
            {card.full_name}
          </Link>
          {card.company_name && (
            <p className="mt-0.5 flex items-center gap-1 truncate text-xs text-muted-foreground">
              <Building className="size-3 shrink-0" />
              <span className="truncate">{card.company_name}</span>
            </p>
          )}
        </div>
        {canMove && (
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="-me-1 -mt-1 shrink-0"
                  aria-label={t('pipeline.moveLabel', { name: card.full_name })}
                  disabled={busy}
                />
              }
            >
              <ArrowRightLeft className="size-3.5" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              <DropdownMenuGroup>
                <DropdownMenuLabel>{t('pipeline.moveTo')}</DropdownMenuLabel>
                {CONTACT_STATUSES.map((s) => (
                  <DropdownMenuItem key={s} disabled={s === card.status} onClick={() => onMove(s)}>
                    <span className="flex-1">{t(`contacts.statuses.${s}`)}</span>
                    {s === card.status && <Check className="size-4" />}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      {card.tags.length > 0 && (
        <div className="mt-2">
          <TagList tags={card.tags} max={2} />
        </div>
      )}
      <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="flex min-w-0 items-center gap-1.5">
          {card.assigned_to_name && <UserAvatar name={card.assigned_to_name} className="size-5 text-[9px]" />}
          <span className="truncate">{card.assigned_to_name ?? t('companies.unassigned')}</span>
        </span>
        <span
          className={cn('flex shrink-0 items-center gap-1', days >= 30 && card.status !== 'won' && card.status !== 'lost' && 'text-warning')}
          title={t('pipeline.daysInStatusTitle')}
        >
          <Clock className="size-3" />
          {days === 0 ? t('pipeline.today') : t('pipeline.days', { count: days })}
        </span>
      </div>
    </article>
  )
}
