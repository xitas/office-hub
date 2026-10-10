import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRightLeft, Check, GripVertical } from 'lucide-react'
import { useState, type DragEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { ErrorState } from '@/components/common'
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
import { api, apiError } from '@/lib/api'
import { usePermission } from '@/lib/permissions'
import { TASK_STATUSES, type Task, type TaskBoardData, type TaskStatus } from '@/lib/tasks'
import { cn } from '@/lib/utils'
import { AssigneeAvatars, DueLabel, PriorityBadge } from './TaskBits'
import { Related } from './TaskList'

// Column accents use theme tokens (they match the status badges), so they work in light and dark mode.
const ACCENT: Record<TaskStatus, string> = {
  todo: 'bg-muted-foreground',
  in_progress: 'bg-primary',
  review: 'bg-warning',
  done: 'bg-success',
}

/** Moves a card between columns in the cached board (optimistic update). */
function moveCard(data: TaskBoardData, id: number, to: TaskStatus): TaskBoardData {
  let moved: Task | undefined
  const columns = data.columns.map((col) => {
    const card = col.cards.find((c) => c.id === id)
    if (!card) return col
    moved = card
    return { ...col, count: col.count - 1, total: col.total - 1, cards: col.cards.filter((c) => c.id !== id) }
  })
  if (!moved) return data
  const card: Task = { ...moved, status: to, is_overdue: to === 'done' ? false : moved.is_overdue }
  return {
    ...data,
    columns: columns.map((col) =>
      col.status === to ? { ...col, count: col.count + 1, total: col.total + 1, cards: [card, ...col.cards] } : col,
    ),
  }
}

/** Kanban: one column per status. Drag on desktop; "Move to…" on phones and for keyboard/screen readers. */
export function TaskBoard({ params, onShowAllDone }: { params: Record<string, string | undefined>; onShowAllDone: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const canMove = usePermission('tasks.edit')
  const [dragging, setDragging] = useState<Task | null>(null)
  const [over, setOver] = useState<TaskStatus | null>(null)
  const key = ['tasks', 'board', params]

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: key,
    queryFn: async () => (await api.get<TaskBoardData>('/tasks/board/', { params })).data,
  })

  const move = useMutation({
    // Same request as the status dropdown on the task page, so permissions and audit are identical.
    mutationFn: async ({ task, to }: { task: Task; to: TaskStatus }) => (await api.patch<Task>(`/tasks/${task.id}/`, { status: to })).data,
    onMutate: ({ task, to }) => queryClient.setQueryData<TaskBoardData>(key, (old) => (old ? moveCard(old, task.id, to) : old)),
    onSuccess: (task) => toast.success(t('tasks.movedTo', { title: task.title, status: t(`tasks.statuses.${task.status}`) })),
    onError: (err) => toast.error(apiError(err).message),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['tasks'] }),
  })
  const requestMove = (task: Task, to: TaskStatus) => {
    if (task.status !== to) move.mutate({ task, to })
  }

  if (isError) return <ErrorState onRetry={() => void refetch()} />
  if (isLoading || !data)
    return (
      <div className="flex gap-3 overflow-hidden">
        {TASK_STATUSES.map((s) => (
          <Skeleton key={s} className="h-96 w-72 shrink-0 rounded-xl lg:w-auto lg:flex-1" />
        ))}
      </div>
    )

  const onDrop = (e: DragEvent, status: TaskStatus) => {
    e.preventDefault()
    setOver(null)
    if (dragging) requestMove(dragging, status)
    setDragging(null)
  }

  return (
    // Columns follow the reading direction, so in Urdu "To do" is on the right.
    <div
      className="-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-3 md:mx-0 md:px-0 lg:grid lg:snap-none lg:grid-cols-4 lg:overflow-visible"
      role="list"
      aria-label={t('tasks.board.label')}
    >
      {data.columns.map((col) => (
        <section
          key={col.status}
          role="listitem"
          aria-label={t('tasks.board.columnLabel', { status: t(`tasks.statuses.${col.status}`), count: col.count })}
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
          <header className="px-3 pt-3 pb-2">
            <div className="flex items-center gap-2">
              <span className={cn('size-2.5 shrink-0 rounded-full', ACCENT[col.status])} aria-hidden />
              <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{t(`tasks.statuses.${col.status}`)}</h2>
              <Badge variant="secondary" className="font-latin tabular-nums">
                {col.count}
              </Badge>
            </div>
            {col.status === 'done' && (
              <p className="mt-1 text-xs text-muted-foreground">{t('tasks.board.doneWindow', { count: data.done_window_days })}</p>
            )}
          </header>
          <ul className="flex min-h-24 flex-1 flex-col gap-2 px-2 pb-2">
            {col.cards.map((task) => (
              <li key={task.id}>
                <BoardCard
                  task={task}
                  canMove={canMove}
                  busy={move.isPending && move.variables?.task.id === task.id}
                  dragging={dragging?.id === task.id}
                  onDragStart={() => setDragging(task)}
                  onDragEnd={() => {
                    setDragging(null)
                    setOver(null)
                  }}
                  onMove={(to) => requestMove(task, to)}
                />
              </li>
            ))}
            {col.cards.length === 0 && (
              <li className="flex flex-1 items-center justify-center rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">
                {canMove ? t('tasks.board.emptyDrop') : t('tasks.board.empty')}
              </li>
            )}
          </ul>
          {col.status === 'done' && col.total > col.count && (
            <Button variant="link" size="sm" className="mb-2 self-center" onClick={onShowAllDone}>
              {t('tasks.board.seeAllDone', { count: col.total })}
            </Button>
          )}
          {col.status !== 'done' && col.count > col.cards.length && (
            <p className="mb-2 px-3 text-center text-xs text-muted-foreground">{t('tasks.board.showing', { shown: col.cards.length, count: col.count })}</p>
          )}
        </section>
      ))}
    </div>
  )
}

function BoardCard({
  task,
  canMove,
  busy,
  dragging,
  onDragStart,
  onDragEnd,
  onMove,
}: {
  task: Task
  canMove: boolean
  busy: boolean
  dragging: boolean
  onDragStart: () => void
  onDragEnd: () => void
  onMove: (to: TaskStatus) => void
}) {
  const { t } = useTranslation()
  return (
    <article
      draggable={canMove}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = 'move'
        e.dataTransfer.setData('text/plain', String(task.id))
        onDragStart()
      }}
      onDragEnd={onDragEnd}
      aria-busy={busy}
      className={cn(
        'group rounded-lg border bg-card p-3 text-sm shadow-card transition-opacity',
        canMove && 'cursor-grab active:cursor-grabbing',
        task.is_overdue && 'border-destructive/40',
        (dragging || busy) && 'opacity-50',
      )}
    >
      <div className="flex items-start gap-1">
        {canMove && <GripVertical className="mt-0.5 hidden size-4 shrink-0 text-muted-foreground/60 md:block" aria-hidden />}
        <div className="min-w-0 flex-1">
          <Link
            to={`/tasks/${task.id}`}
            draggable={false}
            className={cn('line-clamp-2 font-medium hover:text-primary hover:underline', task.status === 'done' && 'text-muted-foreground line-through')}
          >
            {task.title}
          </Link>
          <Related task={task} />
        </div>
        {canMove && (
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="-me-1 -mt-1 shrink-0"
                  aria-label={t('tasks.board.moveLabel', { title: task.title })}
                  disabled={busy}
                />
              }
            >
              <ArrowRightLeft className="size-3.5" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              <DropdownMenuGroup>
                <DropdownMenuLabel>{t('tasks.board.moveTo')}</DropdownMenuLabel>
                {TASK_STATUSES.map((s) => (
                  <DropdownMenuItem key={s} disabled={s === task.status} onClick={() => onMove(s)}>
                    <span className="flex-1">{t(`tasks.statuses.${s}`)}</span>
                    {s === task.status && <Check className="size-4" />}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-xs">
        <PriorityBadge priority={task.priority} />
        {task.due_date && <DueLabel task={task} />}
        <span className="ms-auto">
          <AssigneeAvatars people={task.assignee_details} max={3} />
        </span>
      </div>
    </article>
  )
}
