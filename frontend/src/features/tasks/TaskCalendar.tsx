import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addMonths,
  addWeeks,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameMonth,
  parseISO,
  startOfMonth,
  startOfWeek,
} from 'date-fns'
import { AlarmClock, CalendarX2, ChevronLeft, ChevronRight, Plus } from 'lucide-react'
import { useMemo, useState, type DragEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { ErrorState, FormDialog } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { api, apiError } from '@/lib/api'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { officeDate, type Task, type TaskCalendarData } from '@/lib/tasks'
import { useIsPhone } from '@/lib/useIsPhone'
import { cn } from '@/lib/utils'
import { DueLabel, PriorityBadge } from './TaskBits'

type Mode = 'month' | 'week'
const MODE_KEY = 'crm.tasks.calendarMode'
const MONTH_CHIPS = 3
const LOCALES: Record<string, string> = { en: 'en-PK', ur: 'ur-PK' }

// Priority colours (theme tokens, so they work in light and dark mode).
const CHIP_STYLES: Record<Task['priority'], string> = {
  low: 'border-s-muted-foreground/40 bg-muted/60',
  medium: 'border-s-primary bg-primary/10',
  high: 'border-s-warning bg-warning/15',
  urgent: 'border-s-destructive bg-destructive/10',
}

const iso = (d: Date) => format(d, 'yyyy-MM-dd')

function loadMode(): Mode {
  try {
    return localStorage.getItem(MODE_KEY) === 'week' ? 'week' : 'month'
  } catch {
    return 'month'
  }
}

/** Calendar of due dates. Weeks start on the organization's week-start day; "today" is the office's date. */
export function TaskCalendar({ params, onCreate }: { params: Record<string, string | undefined>; onCreate: (date: string) => void }) {
  const { t, i18n } = useTranslation()
  const fmt = useFormat()
  const isPhone = useIsPhone()
  const queryClient = useQueryClient()
  const canEdit = usePermission('tasks.edit')
  const canCreate = usePermission('tasks.create')
  const locale = LOCALES[i18n.language] ?? 'en-PK'
  const weekStartsOn = fmt.settings.week_start as 0 | 1 | 6
  const officeToday = officeDate(fmt.settings.timezone)

  const [mode, setModeState] = useState<Mode>(loadMode)
  const [anchor, setAnchor] = useState(officeToday)
  const [selected, setSelected] = useState(officeToday)
  const [dragging, setDragging] = useState<Task | null>(null)
  const [over, setOver] = useState<string | null>(null)
  const [picking, setPicking] = useState<Task | null>(null)

  const setMode = (m: Mode) => {
    setModeState(m)
    try {
      localStorage.setItem(MODE_KEY, m)
    } catch {
      // not remembered
    }
  }

  const anchorDate = parseISO(anchor)
  const range = useMemo(() => {
    const anchorDate = parseISO(anchor)
    const first = mode === 'month' ? startOfWeek(startOfMonth(anchorDate), { weekStartsOn }) : startOfWeek(anchorDate, { weekStartsOn })
    const last = mode === 'month' ? endOfWeek(endOfMonth(anchorDate), { weekStartsOn }) : endOfWeek(anchorDate, { weekStartsOn })
    return { start: iso(first), end: iso(last), days: eachDayOfInterval({ start: first, end: last }) }
  }, [anchor, mode, weekStartsOn])

  const { due_from: _from, due_to: _to, ...filters } = params
  const key = ['tasks', 'calendar', filters, range.start, range.end]
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: key,
    queryFn: async () =>
      (await api.get<TaskCalendarData>('/tasks/calendar/', { params: { ...filters, start: range.start, end: range.end } })).data,
  })
  const today = data?.today ?? officeToday

  const byDay = useMemo(() => {
    const map = new Map<string, Task[]>()
    for (const task of data?.tasks ?? []) map.set(task.due_date!, [...(map.get(task.due_date!) ?? []), task])
    return map
  }, [data])

  const reschedule = useMutation({
    mutationFn: async ({ task, date }: { task: Task; date: string | null }) =>
      (await api.patch<Task>(`/tasks/${task.id}/`, date ? { due_date: date } : { due_date: null, due_time: null })).data,
    onMutate: ({ task, date }) =>
      queryClient.setQueryData<TaskCalendarData>(key, (old) => {
        if (!old) return old
        const moved = { ...task, due_date: date, due_time: date ? task.due_time : null }
        const tasks = old.tasks.filter((x) => x.id !== task.id)
        const undated = old.undated.filter((x) => x.id !== task.id)
        return date ? { ...old, tasks: [...tasks, moved], undated } : { ...old, tasks, undated: [moved, ...undated] }
      }),
    onSuccess: (task) =>
      toast.success(
        task.due_date
          ? t('tasks.calendar.moved', { title: task.title, date: fmt.date(`${task.due_date}T12:00:00`) })
          : t('tasks.calendar.undated', { title: task.title }),
      ),
    onError: (err) => toast.error(apiError(err).message),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['tasks'] }),
  })
  const moveTo = (task: Task, date: string | null) => {
    if (task.due_date !== date) reschedule.mutate({ task, date })
  }

  const step = (dir: 1 | -1) => {
    const next = mode === 'month' ? addMonths(anchorDate, dir) : addWeeks(anchorDate, dir)
    setAnchor(iso(next))
    setSelected(iso(mode === 'month' ? startOfMonth(next) : next))
  }
  const goToday = () => {
    setAnchor(today)
    setSelected(today)
  }

  // Dates are plain calendar days: format them at UTC noon so no time zone can shift the day.
  const dayDate = (d: string) => new Date(`${d}T12:00:00Z`)
  const title = new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric', timeZone: 'UTC', numberingSystem: 'latn' }).format(dayDate(anchor))
  const weekTitle = `${fmt.date(`${range.start}T12:00:00`)} – ${fmt.date(`${range.end}T12:00:00`)}`
  const weekday = (d: string, style: 'short' | 'long') => new Intl.DateTimeFormat(locale, { weekday: style, timeZone: 'UTC' }).format(dayDate(d))
  const longDay = (d: string) =>
    new Intl.DateTimeFormat(locale, { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC', numberingSystem: 'latn' }).format(dayDate(d))

  const drop = (e: DragEvent, date: string | null) => {
    e.preventDefault()
    setOver(null)
    if (dragging) moveTo(dragging, date)
    setDragging(null)
  }
  const dropTarget = (date: string | null) =>
    canEdit && !isPhone
      ? {
          onDragOver: (e: DragEvent) => {
            if (!dragging) return
            e.preventDefault()
            e.dataTransfer.dropEffect = 'move'
            setOver(date ?? 'none')
          },
          onDragLeave: (e: DragEvent) => {
            if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node | null)) setOver(null)
          },
          onDrop: (e: DragEvent) => drop(e, date),
        }
      : {}

  const chip = (task: Task, compact = false) => (
    <TaskChip
      key={task.id}
      task={task}
      compact={compact}
      draggable={canEdit && !isPhone}
      dragging={dragging?.id === task.id}
      onDragStart={() => setDragging(task)}
      onDragEnd={() => {
        setDragging(null)
        setOver(null)
      }}
      onPick={isPhone && canEdit ? () => setPicking(task) : undefined}
    />
  )

  const weeks = Array.from({ length: Math.ceil(range.days.length / 7) }, (_, i) => range.days.slice(i * 7, i * 7 + 7))
  const selectedTasks = byDay.get(selected) ?? []

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]">
      <Card className="gap-0 py-0">
        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-2 border-b p-3">
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" onClick={() => step(-1)} aria-label={t(mode === 'month' ? 'tasks.calendar.prevMonth' : 'tasks.calendar.prevWeek')}>
              <ChevronLeft className="size-4 rtl:rotate-180" />
            </Button>
            <Button variant="ghost" size="icon" onClick={() => step(1)} aria-label={t(mode === 'month' ? 'tasks.calendar.nextMonth' : 'tasks.calendar.nextWeek')}>
              <ChevronRight className="size-4 rtl:rotate-180" />
            </Button>
          </div>
          <h2 className="min-w-0 flex-1 truncate text-base font-semibold" aria-live="polite">
            {mode === 'month' ? title : <span className="font-latin">{weekTitle}</span>}
          </h2>
          <Button variant="outline" size="sm" onClick={goToday}>
            {t('tasks.calendar.today')}
          </Button>
          <div role="radiogroup" aria-label={t('tasks.calendar.range')} className="flex rounded-lg bg-muted p-0.5">
            {(['month', 'week'] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                onClick={() => setMode(m)}
                className={cn('rounded-md px-2.5 py-1 text-sm', mode === m ? 'bg-card font-medium shadow-sm' : 'text-muted-foreground hover:text-foreground')}
              >
                {t(`tasks.calendar.${m}`)}
              </button>
            ))}
          </div>
        </div>

        {isError ? (
          <ErrorState onRetry={() => void refetch()} />
        ) : isLoading || !data ? (
          <Skeleton className="m-3 h-96 rounded-lg" />
        ) : isPhone && mode === 'week' ? (
          /* Phones, week: one row per day */
          <ol className="divide-y">
            {range.days.map((d) => {
              const day = iso(d)
              const tasks = byDay.get(day) ?? []
              return (
                <li key={day} className={cn('px-3 py-2.5', day === today && 'bg-primary/5')}>
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <span className={cn('text-sm font-medium', day === today && 'text-primary')}>{longDay(day)}</span>
                    {canCreate && (
                      <Button variant="ghost" size="icon-sm" onClick={() => onCreate(day)} aria-label={t('tasks.calendar.addOn', { date: longDay(day) })}>
                        <Plus className="size-4" />
                      </Button>
                    )}
                  </div>
                  {tasks.length ? <div className="grid gap-1">{tasks.map((task) => chip(task))}</div> : <p className="text-xs text-muted-foreground">{t('tasks.calendar.nothingDue')}</p>}
                </li>
              )
            })}
          </ol>
        ) : (
          <div role="grid" aria-label={mode === 'month' ? title : weekTitle}>
            <div role="row" className="grid grid-cols-7 border-b bg-muted/40">
              {range.days.slice(0, 7).map((d) => (
                <div key={iso(d)} role="columnheader" className="px-1 py-2 text-center text-xs font-medium text-muted-foreground">
                  {weekday(iso(d), isPhone ? 'short' : mode === 'week' ? 'long' : 'short')}
                </div>
              ))}
            </div>
            {weeks.map((week) => (
              <div key={iso(week[0])} role="row" className="grid grid-cols-7 border-b last:border-b-0">
                {week.map((d) => {
                  const day = iso(d)
                  const tasks = byDay.get(day) ?? []
                  const outside = mode === 'month' && !isSameMonth(d, anchorDate)
                  const isToday = day === today
                  if (isPhone) {
                    // Phones, month: compact cells; the selected day's tasks are listed below.
                    return (
                      <button
                        key={day}
                        type="button"
                        role="gridcell"
                        aria-selected={day === selected}
                        aria-label={`${longDay(day)}: ${t('tasks.calendar.taskCount', { count: tasks.length })}`}
                        onClick={() => setSelected(day)}
                        className={cn(
                          'flex min-h-14 flex-col items-center gap-1 border-e py-1.5 last:border-e-0',
                          outside && 'text-muted-foreground/60',
                          day === selected && 'bg-primary/10',
                        )}
                      >
                        <span className={cn('flex size-7 items-center justify-center rounded-full text-sm font-latin', isToday && 'bg-primary text-primary-foreground')}>
                          {d.getDate()}
                        </span>
                        {tasks.length > 0 && (
                          <span className={cn('rounded-full px-1.5 text-[10px] leading-4 font-medium font-latin', tasks.some((x) => x.is_overdue) ? 'bg-destructive/15 text-destructive' : 'bg-muted text-foreground')}>
                            {tasks.length}
                          </span>
                        )}
                      </button>
                    )
                  }
                  const shown = mode === 'month' ? tasks.slice(0, MONTH_CHIPS) : tasks
                  return (
                    <div
                      key={day}
                      role="gridcell"
                      aria-label={longDay(day)}
                      {...dropTarget(day)}
                      className={cn(
                        'group relative flex min-w-0 flex-col gap-1 border-e p-1.5 last:border-e-0',
                        mode === 'month' ? 'min-h-28' : 'min-h-80',
                        outside && 'bg-muted/30',
                        over === day && 'bg-primary/10 ring-2 ring-primary/40 ring-inset',
                      )}
                    >
                      <div className="flex items-center justify-between gap-1">
                        <span
                          className={cn(
                            'flex size-6 items-center justify-center rounded-full text-xs font-medium font-latin',
                            isToday && 'bg-primary text-primary-foreground',
                            outside && !isToday && 'text-muted-foreground',
                          )}
                        >
                          {d.getDate()}
                        </span>
                        {canCreate && (
                          <button
                            type="button"
                            onClick={() => onCreate(day)}
                            className="rounded p-0.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:bg-muted hover:text-foreground focus-visible:opacity-100"
                            aria-label={t('tasks.calendar.addOn', { date: longDay(day) })}
                          >
                            <Plus className="size-3.5" />
                          </button>
                        )}
                      </div>
                      {shown.map((task) => chip(task, mode === 'month'))}
                      {tasks.length > shown.length && (
                        <button
                          type="button"
                          className="self-start rounded px-1 text-xs text-primary hover:underline"
                          onClick={() => {
                            setAnchor(day)
                            setMode('week')
                          }}
                        >
                          {t('tasks.calendar.more', { count: tasks.length - shown.length })}
                        </button>
                      )}
                      {/* Clicking the empty part of a day adds a task due that day. */}
                      {canCreate && (
                        <button
                          type="button"
                          tabIndex={-1}
                          aria-hidden
                          className="min-h-4 flex-1 cursor-copy"
                          onClick={() => onCreate(day)}
                        />
                      )}
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        )}

        {isPhone && mode === 'month' && data && (
          <section className="border-t p-3" aria-label={longDay(selected)}>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{longDay(selected)}</h3>
              {canCreate && (
                <Button size="sm" variant="outline" onClick={() => onCreate(selected)}>
                  <Plus className="size-4" />
                  {t('tasks.add')}
                </Button>
              )}
            </div>
            {selectedTasks.length ? (
              <div className="grid gap-1.5">{selectedTasks.map((task) => chip(task))}</div>
            ) : (
              <p className="text-sm text-muted-foreground">{t('tasks.calendar.nothingDue')}</p>
            )}
          </section>
        )}
      </Card>

      {/* Tasks with no due date: drag one onto a day (desktop) or tap it to pick a date (phones). */}
      <Card
        className={cn('h-fit gap-0 py-0 transition-colors', over === 'none' && 'ring-2 ring-primary/40')}
        {...dropTarget(null)}
        aria-label={t('tasks.calendar.noDate')}
      >
        <div className="flex items-center gap-2 border-b px-3 py-2.5">
          <CalendarX2 className="size-4 text-muted-foreground" />
          <h2 className="flex-1 text-sm font-semibold">{t('tasks.calendar.noDate')}</h2>
          {data && <span className="text-xs text-muted-foreground font-latin">{data.undated_count}</span>}
        </div>
        <div className="grid gap-1.5 p-2">
          {data?.undated.length ? (
            data.undated.map((task) => chip(task))
          ) : (
            <p className="px-1 py-3 text-center text-xs text-muted-foreground">{t('tasks.calendar.noUndated')}</p>
          )}
          {data && data.undated_count > data.undated.length && (
            <p className="px-1 text-xs text-muted-foreground">{t('tasks.calendar.undatedMore', { count: data.undated_count - data.undated.length })}</p>
          )}
          {canEdit && !isPhone && data && data.undated.length > 0 && <p className="px-1 pb-1 text-xs text-muted-foreground">{t('tasks.calendar.dragHint')}</p>}
        </div>
      </Card>

      {picking && <DatePickDialog task={picking} onClose={() => setPicking(null)} onPick={(date) => moveTo(picking, date)} />}
    </div>
  )
}

function TaskChip({
  task,
  compact,
  draggable,
  dragging,
  onDragStart,
  onDragEnd,
  onPick,
}: {
  task: Task
  compact?: boolean
  draggable: boolean
  dragging: boolean
  onDragStart: () => void
  onDragEnd: () => void
  /** Phones: a tap opens the date picker instead of the task page. */
  onPick?: () => void
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const label = `${task.title}${task.is_overdue ? ` (${t('tasks.overdue')})` : ''}`
  return (
    <button
      type="button"
      draggable={draggable}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = 'move'
        e.dataTransfer.setData('text/plain', String(task.id))
        onDragStart()
      }}
      onDragEnd={onDragEnd}
      onClick={(e) => {
        e.stopPropagation()
        if (onPick) onPick()
        else navigate(`/tasks/${task.id}`)
      }}
      title={label}
      aria-label={label}
      className={cn(
        'flex w-full min-w-0 items-center gap-1 rounded border-s-4 px-1.5 py-0.5 text-start text-xs transition-opacity hover:brightness-95 dark:hover:brightness-125',
        CHIP_STYLES[task.priority],
        task.is_overdue && 'text-destructive ring-1 ring-destructive/50',
        task.status === 'done' && 'text-muted-foreground line-through opacity-70',
        draggable && 'cursor-grab active:cursor-grabbing',
        dragging && 'opacity-40',
        !compact && 'py-1.5 text-sm',
      )}
    >
      {task.is_overdue && <AlarmClock className="size-3 shrink-0" />}
      {/* dir=auto: an English title in the Urdu UI is cut at its end, not its start */}
      <span dir="auto" className="min-w-0 flex-1 truncate">
        {task.title}
      </span>
      {task.due_time && !compact && <span className="shrink-0 text-[11px] text-muted-foreground font-latin">{task.due_time.slice(0, 5)}</span>}
    </button>
  )
}

/** Phones: open the task, or move it to another day with a date picker. */
function DatePickDialog({ task, onClose, onPick }: { task: Task; onClose: () => void; onPick: (date: string | null) => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [date, setDate] = useState(task.due_date ?? '')
  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={task.title}>
      <div className="grid gap-4">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <PriorityBadge priority={task.priority} />
          <DueLabel task={task} />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="cal-move-date">{t('tasks.calendar.moveToDate')}</Label>
          <Input id="cal-move-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} className="font-latin" />
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          {task.due_date && (
            <Button
              variant="ghost"
              onClick={() => {
                onPick(null)
                onClose()
              }}
            >
              {t('tasks.calendar.removeDate')}
            </Button>
          )}
          <Button variant="outline" onClick={() => navigate(`/tasks/${task.id}`)}>
            {t('tasks.calendar.openTask')}
          </Button>
          <Button
            disabled={!date || date === task.due_date}
            onClick={() => {
              onPick(date)
              onClose()
            }}
          >
            {t('tasks.calendar.move')}
          </Button>
        </div>
      </div>
    </FormDialog>
  )
}

