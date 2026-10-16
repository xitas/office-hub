import { useQuery } from '@tanstack/react-query'
import { CalendarCheck, ChevronLeft, ChevronRight, DoorOpen, Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { EmptyState, ErrorState, PageHeader, SimpleSelect } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api } from '@/lib/api'
import {
  RESOURCE_TYPES,
  addDays,
  freeRanges,
  minutesOf,
  officeParts,
  placeBookings,
  timeOf,
  todayInOffice,
  useBookingsRange,
  useResources,
  weekStartOf,
  type Booking,
  type Resource,
} from '@/lib/bookings'
import { useFormat } from '@/lib/format'
import { useIsPhone } from '@/lib/useIsPhone'
import { cn } from '@/lib/utils'
import { BookingDetails, StatusBadge } from './BookingDetails'
import { BookingDialog, type BookingDraft } from './BookingDialog'
import { Timeline, type TimelineRow } from './Timeline'

function useNowMinutes(tz: string) {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 60_000)
    return () => window.clearInterval(id)
  }, [])
  return minutesOf(officeParts(tz, now).time)
}

/** Resource bookings: a day (all resources) or week (one resource) timeline with free slots; a simple list on phones. */
export function BookingsPage() {
  const { t, i18n } = useTranslation()
  const fmt = useFormat()
  const tz = fmt.settings.timezone
  const isPhone = useIsPhone()
  const [params, setParams] = useSearchParams()
  const today = todayInOffice(tz)
  const date = params.get('date') ?? today
  const view = !isPhone && params.get('view') === 'week' ? 'week' : 'day'
  const type = params.get('type') ?? ''
  const { data: allResources, isLoading: loadingResources, isError, refetch } = useResources({ active: true })
  const resources = (allResources ?? []).filter((r) => !type || r.type === type)
  const weekResource = Number(params.get('resource')) || resources[0]?.id
  const from = view === 'week' ? weekStartOf(date, fmt.settings.week_start) : date
  const to = view === 'week' ? addDays(from, 6) : date
  const { data: bookings, isLoading } = useBookingsRange(from, to, view === 'week' ? weekResource : undefined)
  const nowMinutes = useNowMinutes(tz)
  const [draft, setDraft] = useState<BookingDraft | null>(null)
  const [picked, setOpened] = useState<Booking | null>(null)

  const set = (changes: Record<string, string | undefined>) =>
    setParams((p) => {
      for (const [k, v] of Object.entries(changes)) {
        if (v) p.set(k, v)
        else p.delete(k)
      }
      return p
    }, { replace: true })

  // A link to one booking (notifications, dashboard) opens it.
  const linked = Number(params.get('booking')) || null
  const { data: linkedBooking } = useQuery({
    queryKey: ['bookings', 'one', linked],
    queryFn: async () => (await api.get<Booking>(`/bookings/${linked}/`)).data,
    enabled: !!linked,
  })
  const opened = picked ?? linkedBooking ?? null

  const step = view === 'week' ? 7 : 1
  const rows: TimelineRow[] =
    view === 'week'
      ? Array.from({ length: 7 }, (_, i) => {
          const d = addDays(from, i)
          return { key: d, label: fmt.date(`${d}T12:00:00`), sublabel: weekdayLabel(d, i18n.language), resource: weekResource ?? 0, date: d }
        })
      : resources.map((r) => ({ key: String(r.id), label: r.name, sublabel: describe(r, t), resource: r.id, date }))

  const onSelect = (row: TimelineRow, start: number, end: number) =>
    setDraft({ resource: row.resource, date: row.date, start: timeOf(start), end: timeOf(end) })

  return (
    <>
      <PageHeader
        title={t('bookings.pageTitle')}
        subtitle={t('bookings.pageSubtitle')}
        actions={
          <>
            <Button variant="outline" nativeButton={false} render={<Link to="/bookings/mine" />}>
              <CalendarCheck className="size-4" />
              {t('bookings.mine')}
            </Button>
            <Button variant="outline" nativeButton={false} render={<Link to="/resources" />}>
              <DoorOpen className="size-4" />
              {t('nav.resources')}
            </Button>
            <Button onClick={() => setDraft({ date: date < today ? today : date })}>
              <Plus className="size-4" />
              {t('bookings.new')}
            </Button>
          </>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon" aria-label={t('bookings.previous')} onClick={() => set({ date: addDays(date, -step) })}>
            <ChevronLeft className="size-4 rtl:rotate-180" />
          </Button>
          <Button variant="outline" onClick={() => set({ date: undefined })} disabled={date === today}>
            {t('bookings.today')}
          </Button>
          <Button variant="outline" size="icon" aria-label={t('bookings.next')} onClick={() => set({ date: addDays(date, step) })}>
            <ChevronRight className="size-4 rtl:rotate-180" />
          </Button>
        </div>
        <Input
          type="date"
          value={date}
          onChange={(e) => e.target.value && set({ date: e.target.value })}
          aria-label={t('bookings.date')}
          className="w-40 font-latin"
        />
        {!isPhone && (
          <Tabs value={view} onValueChange={(v) => set({ view: v === 'week' ? 'week' : undefined })}>
            <TabsList>
              <TabsTrigger value="day">{t('bookings.day')}</TabsTrigger>
              <TabsTrigger value="week">{t('bookings.week')}</TabsTrigger>
            </TabsList>
          </Tabs>
        )}
        <div className="w-44">
          <SimpleSelect
            id="bk-type"
            value={type}
            onChange={(v) => set({ type: v || undefined, resource: undefined })}
            options={[{ value: '', label: t('resources.allTypes') }, ...RESOURCE_TYPES.map((r) => ({ value: r, label: t(`resources.types.${r}`) }))]}
          />
        </div>
        {view === 'week' && resources.length > 0 && (
          <div className="w-56">
            <SimpleSelect
              id="bk-week-resource"
              value={String(weekResource)}
              onChange={(v) => set({ resource: v })}
              options={resources.map((r) => ({ value: String(r.id), label: r.name }))}
            />
          </div>
        )}
        <p className="ms-auto text-sm font-medium text-muted-foreground" dir={view === 'week' ? 'ltr' : undefined}>
          {view === 'week' ? `${fmt.date(`${from}T12:00:00`)} – ${fmt.date(`${to}T12:00:00`)}` : `${weekdayLabel(date, i18n.language)} ${fmt.date(`${date}T12:00:00`)}`}
        </p>
      </div>

      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : loadingResources || isLoading ? (
        <Skeleton className="h-72 rounded-xl" />
      ) : !resources.length ? (
        <EmptyState icon={DoorOpen} title={t('resources.empty')} hint={t('resources.emptyHint')} className="py-16" />
      ) : isPhone ? (
        <PhoneDay resources={resources} bookings={bookings ?? []} date={date} today={today} nowMinutes={nowMinutes} onBook={setDraft} onOpen={setOpened} />
      ) : (
        <>
          <Timeline rows={rows} bookings={bookings ?? []} today={today} nowMinutes={nowMinutes} onSelect={onSelect} onOpen={setOpened} />
          <Legend />
        </>
      )}

      {draft && <BookingDialog draft={draft} onClose={() => setDraft(null)} />}
      {opened && (
        <BookingDetails
          booking={opened}
          onClose={() => {
            setOpened(null)
            if (linked) set({ booking: undefined })
          }}
        />
      )}
    </>
  )
}

function weekdayLabel(date: string, language: string) {
  const locale = language === 'ur' ? 'ur-PK' : 'en-GB'
  return new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' }).format(new Date(`${date}T12:00:00Z`))
}

function describe(r: Resource, t: (key: string, o?: Record<string, unknown>) => string) {
  const bits = [t(`resources.types.${r.type}`)]
  if (r.capacity) bits.push(t('resources.seats', { count: r.capacity }))
  if (r.needs_approval) bits.push(t('resources.needsApproval'))
  return bits.join(' · ')
}

function Legend() {
  const { t } = useTranslation()
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <span className="flex items-center gap-1.5"><span className="size-3 rounded-sm bg-primary" />{t('bookings.legendMine')}</span>
      <span className="flex items-center gap-1.5"><span className="size-3 rounded-sm border bg-secondary" />{t('bookings.legendOthers')}</span>
      <span className="flex items-center gap-1.5"><span className="size-3 rounded-sm border border-dashed border-amber-500 bg-amber-50 dark:bg-amber-500/15" />{t('bookings.legendPending')}</span>
      <span className="flex items-center gap-1.5"><span className="size-3 rounded-sm border bg-card" />{t('bookings.legendFree')}</span>
      <span>{t('bookings.dragHint')}</span>
    </div>
  )
}

/** Phones: each resource with what's booked and when it's free, and a Book button. */
function PhoneDay({
  resources,
  bookings,
  date,
  today,
  nowMinutes,
  onBook,
  onOpen,
}: {
  resources: Resource[]
  bookings: Booking[]
  date: string
  today: string
  nowMinutes: number
  onBook: (draft: BookingDraft) => void
  onOpen: (booking: Booking) => void
}) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const tz = fmt.settings.timezone
  const opens = minutesOf(fmt.settings.office_opens)
  const closes = minutesOf(fmt.settings.office_closes)
  const past = date < today
  return (
    <ul className="grid gap-3">
      {resources.map((r) => {
        const placed = placeBookings(bookings, r.id, date, tz).sort((a, b) => a.start - b.start)
        const free = past ? [] : freeRanges(placed, opens, closes, date === today ? nowMinutes : 0)
        return (
          <li key={r.id}>
            <Card className="gap-2 py-3">
              <CardContent className="grid gap-2 px-3">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <bdi className="block truncate font-medium">{r.name}</bdi>
                    <span className="block text-xs text-muted-foreground">{describe(r, t)}</span>
                  </div>
                  <Button
                    size="sm"
                    disabled={!free.length}
                    onClick={() => onBook({ resource: r.id, date, start: timeOf(free[0][0]), end: timeOf(Math.min(free[0][0] + 60, free[0][1])) })}
                  >
                    {t('bookings.book')}
                  </Button>
                </div>
                {placed.length > 0 && (
                  <ul className="grid gap-1">
                    {placed.map(({ booking: b, start, end }) => (
                      <li key={b.id}>
                        <button
                          type="button"
                          onClick={() => onOpen(b)}
                          className={cn('flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-start text-sm', b.status === 'pending' && 'border-dashed border-amber-500')}
                        >
                          <span className="shrink-0 text-xs">{fmt.clock(timeOf(start))}–{fmt.clock(timeOf(end))}</span>
                          <bdi className="min-w-0 flex-1 truncate">{b.title}</bdi>
                          {b.status === 'pending' && <StatusBadge status="pending" />}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="text-xs text-muted-foreground">
                  {free.length ? (
                    <>
                      {t('bookings.freeAt')}{' '}
                      {free.map(([s, e], i) => (
                        <Badge key={i} variant="outline" className="me-1 mt-1 font-normal">
                          {fmt.clock(timeOf(s))}–{fmt.clock(timeOf(e))}
                        </Badge>
                      ))}
                    </>
                  ) : (
                    t('bookings.noFreeTime')
                  )}
                </p>
              </CardContent>
            </Card>
          </li>
        )
      })}
    </ul>
  )
}
