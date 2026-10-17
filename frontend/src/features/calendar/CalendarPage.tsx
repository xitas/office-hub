import { CalendarCheck, CalendarDays, CheckSquare, ChevronLeft, ChevronRight, DoorOpen, MapPin, Palmtree, PartyPopper, Plus, Users } from 'lucide-react'
import { isSameMonth, parseISO } from 'date-fns'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ErrorState, PageHeader } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { minutesOf, officeParts, todayInOffice } from '@/lib/bookings'
import {
  CALENDAR_LAYERS,
  LAYER_OF,
  TYPE_DOTS,
  TYPE_STYLES,
  calendarRange,
  calendarTitles,
  isoDay,
  itemDays,
  stepAnchor,
  useAllowedKinds,
  useCalendar,
  type CalendarItem,
  type CalendarLayer,
  type CalendarMode,
} from '@/lib/calendar'
import { useFormat } from '@/lib/format'
import { useIsPhone } from '@/lib/useIsPhone'
import { cn } from '@/lib/utils'
import { EventDetails } from './EventDetails'
import { EventDialog, type EventDraft } from './EventDialog'

const LOCALES: Record<string, string> = { en: 'en-PK', ur: 'ur-PK' }
const LAYERS_KEY = 'crm.calendar.layers'
const MONTH_CHIPS = 3
const HOUR_PX = 48
const ICONS = { meeting: Users, event: PartyPopper, holiday: CalendarDays, task: CheckSquare, booking: DoorOpen, leave: Palmtree, visit: MapPin }

function loadLayers(): CalendarLayer[] {
  try {
    const saved = JSON.parse(localStorage.getItem(LAYERS_KEY) ?? 'null') as string[] | null
    const valid = saved?.filter((l): l is CalendarLayer => (CALENDAR_LAYERS as readonly string[]).includes(l))
    if (valid?.length) return valid
  } catch {
    // not remembered
  }
  return [...CALENDAR_LAYERS]
}

/** The shared office calendar: meetings, office events, holidays, my task deadlines and my bookings. */
export function CalendarPage() {
  const { t, i18n } = useTranslation()
  const fmt = useFormat()
  const tz = fmt.settings.timezone
  const isPhone = useIsPhone()
  const navigate = useNavigate()
  const locale = LOCALES[i18n.language] ?? 'en-PK'
  const weekStartsOn = fmt.settings.week_start as 0 | 1 | 6
  const officeToday = todayInOffice(tz)
  const [params, setParams] = useSearchParams()
  const anchor = params.get('date') ?? officeToday
  const mode: CalendarMode = (['month', 'week', 'day'] as const).find((m) => m === params.get('view')) ?? 'month'
  const [layers, setLayersState] = useState<CalendarLayer[]>(loadLayers)
  const [draft, setDraft] = useState<EventDraft | null>(null)
  const [selected, setSelected] = useState(anchor)
  const kinds = useAllowedKinds()
  const set = (changes: Record<string, string | undefined>) =>
    setParams((p) => {
      for (const [k, v] of Object.entries(changes)) {
        if (v) p.set(k, v)
        else p.delete(k)
      }
      return p
    }, { replace: true })

  const range = useMemo(() => calendarRange(anchor, mode, weekStartsOn), [anchor, mode, weekStartsOn])
  const { data, isLoading, isError, refetch } = useCalendar(range.start, range.end, layers)
  const today = data?.today ?? officeToday
  const titles = calendarTitles(locale, anchor, range)
  const officeDay = (iso: string) => officeParts(tz, iso).date

  const byDay = useMemo(() => {
    const map = new Map<string, CalendarItem[]>()
    for (const item of data?.items ?? []) {
      const [first, last] = itemDays(item, (iso) => officeParts(tz, iso).date)
      for (const d of range.days) {
        const day = isoDay(d)
        if (day >= first && day <= last) map.set(day, [...(map.get(day) ?? []), item])
      }
    }
    return map
  }, [data, range, tz])

  const toggleLayer = (layer: CalendarLayer) => {
    const next = layers.includes(layer) ? layers.filter((l) => l !== layer) : [...layers, layer]
    setLayersState(next)
    try {
      localStorage.setItem(LAYERS_KEY, JSON.stringify(next))
    } catch {
      // not remembered
    }
  }
  const open = (item: CalendarItem) => {
    if (item.url) navigate(item.url)
    else set({ event: String(item.id) })
  }
  const newOn = (date: string, start?: string) => setDraft({ date, start })
  const showDay = (day: string) => set({ date: day, view: 'day' })
  const openedId = Number(params.get('event')) || null
  const creating = draft ?? (params.get('new') ? { date: anchor } : null)

  const chip = (item: CalendarItem, compact = false) => {
    const Icon = ICONS[item.type]
    const time = item.all_day ? null : fmt.clock(officeParts(tz, item.start).time)
    return (
      <button
        key={item.key}
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          open(item)
        }}
        className={cn(
          'flex w-full min-w-0 items-center gap-1 rounded-md border px-1.5 py-0.5 text-start text-xs',
          TYPE_STYLES[item.type],
          item.type === 'task' && item.is_overdue && 'border-destructive/50 text-destructive',
          item.room_status === 'pending' && 'border-dashed',
          !compact && 'py-1 text-sm',
        )}
        title={item.title}
      >
        <Icon className="size-3 shrink-0" />
        {time && <span dir="ltr" className="shrink-0 font-latin opacity-80">{time}</span>}
        <span dir="auto" className="min-w-0 flex-1 truncate">{item.subtitle ? `${item.title} · ${item.subtitle}` : item.title}</span>
      </button>
    )
  }

  const toolbar = (
    <div className="flex flex-wrap items-center gap-2 border-b p-3">
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="icon" onClick={() => set({ date: stepAnchor(anchor, mode, -1) })} aria-label={t('calendar.previous')}>
          <ChevronLeft className="size-4 rtl:rotate-180" />
        </Button>
        <Button variant="ghost" size="icon" onClick={() => set({ date: stepAnchor(anchor, mode, 1) })} aria-label={t('calendar.next')}>
          <ChevronRight className="size-4 rtl:rotate-180" />
        </Button>
      </div>
      <h2 className="min-w-0 flex-1 truncate text-base font-semibold" aria-live="polite">
        {mode === 'month' ? titles.month : mode === 'week' ? titles.week : titles.longDay(anchor)}
      </h2>
      <Button variant="outline" size="sm" onClick={() => set({ date: undefined })} disabled={anchor === today}>
        {t('calendar.today')}
      </Button>
      <div role="radiogroup" aria-label={t('calendar.view')} className="flex rounded-lg bg-muted p-0.5">
        {(['month', 'week', 'day'] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={mode === m}
            onClick={() => set({ view: m === 'month' ? undefined : m })}
            className={cn('rounded-md px-2.5 py-1 text-sm', mode === m ? 'bg-card font-medium shadow-sm' : 'text-muted-foreground hover:text-foreground')}
          >
            {t(`calendar.views.${m}`)}
          </button>
        ))}
      </div>
    </div>
  )

  const layerBar = (
    <div className="flex flex-wrap items-center gap-1.5 border-b px-3 py-2" role="group" aria-label={t('calendar.show')}>
      {CALENDAR_LAYERS.map((layer) => {
        const type = (Object.keys(LAYER_OF) as (keyof typeof LAYER_OF)[]).find((k) => LAYER_OF[k] === layer)!
        const on = layers.includes(layer)
        return (
          <button
            key={layer}
            type="button"
            aria-pressed={on}
            onClick={() => toggleLayer(layer)}
            className={cn('flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs', on ? 'bg-card' : 'text-muted-foreground opacity-60')}
          >
            <span className={cn('size-2 rounded-full', TYPE_DOTS[type], !on && 'opacity-40')} />
            {t(`calendar.layers.${layer}`)}
          </button>
        )
      })}
    </div>
  )

  const weeks = Array.from({ length: Math.ceil(range.days.length / 7) }, (_, i) => range.days.slice(i * 7, i * 7 + 7))
  const anchorDate = parseISO(anchor)

  return (
    <>
      <PageHeader
        title={t('calendar.pageTitle')}
        subtitle={t('calendar.pageSubtitle')}
        actions={
          <Button onClick={() => setDraft({ date: anchor < today ? today : anchor })}>
            <Plus className="size-4" />
            {kinds.length > 1 ? t('calendar.add') : t('calendar.new.meeting')}
          </Button>
        }
      />
      <Card className="gap-0 py-0">
        {toolbar}
        {layerBar}
        {isError ? (
          <ErrorState onRetry={() => void refetch()} />
        ) : isLoading || !data ? (
          <Skeleton className="m-3 h-96 rounded-lg" />
        ) : mode === 'day' ? (
          <DayView day={anchor} items={byDay.get(anchor) ?? []} chip={chip} onNew={newOn} isToday={anchor === today} officeDay={officeDay} />
        ) : isPhone && mode === 'week' ? (
          <ol className="divide-y">
            {range.days.map((d) => {
              const day = isoDay(d)
              const items = byDay.get(day) ?? []
              return (
                <li key={day} className={cn('px-3 py-2.5', day === today && 'bg-primary/5')}>
                  <button type="button" onClick={() => showDay(day)} className={cn('mb-1.5 text-sm font-medium', day === today && 'text-primary')}>
                    {titles.longDay(day)}
                  </button>
                  {items.length ? <div className="grid gap-1">{items.map((i) => chip(i))}</div> : <p className="text-xs text-muted-foreground">{t('calendar.nothing')}</p>}
                </li>
              )
            })}
          </ol>
        ) : (
          <div role="grid" aria-label={mode === 'month' ? titles.month : titles.week}>
            <div role="row" className="grid grid-cols-7 border-b bg-muted/40">
              {range.days.slice(0, 7).map((d) => (
                <div key={isoDay(d)} role="columnheader" className="px-1 py-2 text-center text-xs font-medium text-muted-foreground">
                  {titles.weekday(isoDay(d), isPhone ? 'short' : mode === 'week' ? 'long' : 'short')}
                </div>
              ))}
            </div>
            {weeks.map((week) => (
              <div key={isoDay(week[0])} role="row" className="grid grid-cols-7 border-b last:border-b-0">
                {week.map((d) => {
                  const day = isoDay(d)
                  const items = byDay.get(day) ?? []
                  const outside = mode === 'month' && !isSameMonth(d, anchorDate)
                  const isToday = day === today
                  const holiday = items.some((i) => i.type === 'holiday')
                  if (isPhone) {
                    return (
                      <button
                        key={day}
                        type="button"
                        role="gridcell"
                        aria-selected={day === selected}
                        aria-label={`${titles.longDay(day)}: ${t('calendar.itemCount', { count: items.length })}`}
                        onClick={() => setSelected(day)}
                        className={cn('flex min-h-14 flex-col items-center gap-1 border-e py-1.5 last:border-e-0', outside && 'text-muted-foreground/60', day === selected && 'bg-primary/10', holiday && 'bg-emerald-500/10')}
                      >
                        <span className={cn('flex size-7 items-center justify-center rounded-full text-sm font-latin', isToday && 'bg-primary text-primary-foreground')}>{d.getDate()}</span>
                        <span className="flex gap-0.5">
                          {[...new Set(items.map((i) => i.type))].slice(0, 4).map((type) => (
                            <span key={type} className={cn('size-1.5 rounded-full', TYPE_DOTS[type])} />
                          ))}
                        </span>
                      </button>
                    )
                  }
                  const shown = mode === 'month' ? items.slice(0, MONTH_CHIPS) : items
                  return (
                    <div
                      key={day}
                      role="gridcell"
                      aria-label={titles.longDay(day)}
                      className={cn(
                        'group relative flex min-w-0 flex-col gap-1 border-e p-1.5 last:border-e-0',
                        mode === 'month' ? 'min-h-28' : 'min-h-96',
                        outside && 'bg-muted/30',
                        holiday && 'bg-emerald-500/5',
                      )}
                    >
                      <div className="flex items-center justify-between gap-1">
                        <button
                          type="button"
                          onClick={() => showDay(day)}
                          className={cn(
                            'flex size-6 items-center justify-center rounded-full text-xs font-medium font-latin hover:bg-muted',
                            isToday && 'bg-primary text-primary-foreground hover:bg-primary',
                            outside && !isToday && 'text-muted-foreground',
                          )}
                          aria-label={t('calendar.openDay', { date: titles.longDay(day) })}
                        >
                          {d.getDate()}
                        </button>
                        <button
                          type="button"
                          onClick={() => newOn(day)}
                          className="rounded p-0.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:bg-muted hover:text-foreground focus-visible:opacity-100"
                          aria-label={t('calendar.addOn', { date: titles.longDay(day) })}
                        >
                          <Plus className="size-3.5" />
                        </button>
                      </div>
                      {shown.map((item) => chip(item, mode === 'month'))}
                      {items.length > shown.length && (
                        <button type="button" className="self-start rounded px-1 text-xs text-primary hover:underline" onClick={() => showDay(day)}>
                          {t('calendar.more', { count: items.length - shown.length })}
                        </button>
                      )}
                      <button type="button" tabIndex={-1} aria-hidden className="min-h-4 flex-1 cursor-copy" onClick={() => newOn(day)} />
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        )}
        {isPhone && mode === 'month' && data && (
          <section className="border-t p-3" aria-label={titles.longDay(selected)}>
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{titles.longDay(selected)}</h3>
              <Button size="sm" variant="outline" onClick={() => newOn(selected)}>
                <Plus className="size-4" />
                {t('calendar.add')}
              </Button>
            </div>
            {(byDay.get(selected) ?? []).length ? (
              <div className="grid gap-1.5">{(byDay.get(selected) ?? []).map((i) => chip(i))}</div>
            ) : (
              <p className="text-sm text-muted-foreground">{t('calendar.nothing')}</p>
            )}
          </section>
        )}
      </Card>
      <p className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
        <CalendarCheck className="size-3.5" />
        {t('calendar.hint')}
      </p>

      {creating && (
        <EventDialog
          draft={creating}
          onClose={() => {
            setDraft(null)
            if (params.get('new')) set({ new: undefined })
          }}
        />
      )}
      {openedId && <EventDetails id={openedId} onClose={() => set({ event: undefined })} />}
    </>
  )
}

/** One day: all-day items on top, then the hours with timed items placed by time (side by side when they overlap). */
function DayView({
  day,
  items,
  chip,
  onNew,
  isToday,
  officeDay,
}: {
  day: string
  items: CalendarItem[]
  chip: (item: CalendarItem, compact?: boolean) => React.ReactNode
  onNew: (date: string, start?: string) => void
  isToday: boolean
  officeDay: (iso: string) => string
}) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const tz = fmt.settings.timezone
  const allDay = items.filter((i) => i.all_day)
  const placed = items
    .filter((i) => !i.all_day)
    .map((i) => {
      const s = officeParts(tz, i.start)
      const e = officeParts(tz, i.end)
      const start = s.date < day ? 0 : minutesOf(s.time)
      const end = e.date > day || officeDay(i.end) > day ? 24 * 60 : Math.max(minutesOf(e.time), start + 15)
      return { item: i, start, end, col: 0, cols: 1 }
    })
    .sort((a, b) => a.start - b.start || b.end - a.end)
  // Overlapping items share the width: a simple column assignment per cluster.
  let cluster: typeof placed = []
  let clusterEnd = -1
  const flush = () => {
    const cols = Math.max(1, ...cluster.map((p) => p.col + 1))
    for (const p of cluster) p.cols = cols
    cluster = []
  }
  for (const p of placed) {
    if (p.start >= clusterEnd) {
      flush()
      clusterEnd = p.end
    }
    const used = new Set(cluster.filter((c) => c.end > p.start).map((c) => c.col))
    while (used.has(p.col)) p.col++
    cluster.push(p)
    clusterEnd = Math.max(clusterEnd, p.end)
  }
  flush()
  const firstHour = Math.min(Math.floor(minutesOf(fmt.settings.office_opens) / 60), ...placed.map((p) => Math.floor(p.start / 60)))
  const lastHour = Math.max(Math.ceil(minutesOf(fmt.settings.office_closes) / 60), ...placed.map((p) => Math.ceil(p.end / 60)))
  const hours = Array.from({ length: Math.max(1, lastHour - firstHour) }, (_, i) => firstHour + i)
  const [opened] = useState(() => new Date())
  const now = isToday ? minutesOf(officeParts(tz, opened).time) : null

  return (
    <div className="grid gap-2 p-3">
      {allDay.length > 0 && <div className="grid gap-1">{allDay.map((i) => chip(i))}</div>}
      <div className="relative flex">
        <div className="w-20 shrink-0">
          {hours.map((h) => (
            <div key={h} className="text-end text-[11px] text-muted-foreground font-latin" style={{ height: HOUR_PX }} dir="ltr">
              <span className="relative -top-2 whitespace-nowrap pe-2">{fmt.clock(`${String(h).padStart(2, '0')}:00`)}</span>
            </div>
          ))}
        </div>
        <div className="relative flex-1 border-s">
          {hours.map((h) => (
            <button
              key={h}
              type="button"
              aria-label={t('calendar.addAt', { time: fmt.clock(`${String(h).padStart(2, '0')}:00`) })}
              onClick={() => onNew(day, `${String(h).padStart(2, '0')}:00`)}
              className="block w-full border-b border-border/60 hover:bg-primary/5"
              style={{ height: HOUR_PX }}
            />
          ))}
          {now !== null && now >= firstHour * 60 && now <= lastHour * 60 && (
            <div className="pointer-events-none absolute inset-x-0 h-0.5 bg-destructive/70" style={{ top: ((now - firstHour * 60) / 60) * HOUR_PX }} />
          )}
          {placed.map((p) => (
            <div
              key={p.item.key}
              className="absolute p-0.5"
              style={{
                top: ((p.start - firstHour * 60) / 60) * HOUR_PX,
                height: Math.max(((p.end - p.start) / 60) * HOUR_PX, 22),
                insetInlineStart: `${(p.col / p.cols) * 100}%`,
                width: `${100 / p.cols}%`,
              }}
            >
              {/* An opaque backing, so the hour lines don't show through the tinted item. */}
              <div className="h-full rounded-md bg-card [&>button]:h-full [&>button]:items-start">{chip(p.item)}</div>
            </div>
          ))}
        </div>
      </div>
      {!items.length && <p className="text-center text-sm text-muted-foreground">{t('calendar.nothing')}</p>}
    </div>
  )
}
