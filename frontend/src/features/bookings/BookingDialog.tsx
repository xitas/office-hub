import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Info, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { FormDialog, FormField, SimpleSelect } from '@/components/common'
import { PeoplePicker } from '@/components/common/PeoplePicker'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import {
  BOOKINGS_KEY,
  addDays,
  isoWeekday,
  minutesOf,
  officeMoment,
  officeParts,
  timeOf,
  todayInOffice,
  useResources,
  type Booking,
  type Occurrence,
} from '@/lib/bookings'
import { useFormat } from '@/lib/format'
import { useUserOptions } from '@/lib/queries'
import { weekdayName } from '@/lib/tasks'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { cn } from '@/lib/utils'

export interface BookingDraft {
  resource?: number
  date?: string
  start?: string // "HH:MM" office time
  end?: string
}

/** Book a resource (once, or weekly on chosen days until a date), or change a booking. */
export function BookingDialog({ booking, draft, onClose }: { booking?: Booking; draft?: BookingDraft; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const me = useMe()
  const fmt = useFormat()
  const tz = fmt.settings.timezone
  const queryClient = useQueryClient()
  const { data: resources } = useResources({ active: true })
  const { data: users } = useUserOptions()
  const opens = minutesOf(fmt.settings.office_opens)
  const closes = minutesOf(fmt.settings.office_closes)
  const initial = booking ? { start: officeParts(tz, booking.start), end: officeParts(tz, booking.end) } : null

  const [resource, setResource] = useState<number | undefined>(booking?.resource ?? draft?.resource)
  const [title, setTitle] = useState(booking?.title ?? '')
  const [date, setDate] = useState(initial?.start.date ?? draft?.date ?? todayInOffice(tz))
  // Today: the next free quarter hour within office hours (a time that has passed can't be booked).
  const [nowMinutes] = useState(() => minutesOf(officeParts(tz, new Date()).time))
  const defaultStart =
    (draft?.date ?? todayInOffice(tz)) === todayInOffice(tz) ? timeOf(Math.min(Math.max(opens, Math.ceil((nowMinutes + 1) / 15) * 15), closes - 15)) : timeOf(opens)
  const [start, setStart] = useState(initial?.start.time ?? draft?.start ?? defaultStart)
  const [end, setEnd] = useState(initial?.end.time ?? draft?.end ?? timeOf(Math.min(minutesOf(draft?.start ?? defaultStart) + 60, closes)))
  const [attendees, setAttendees] = useState<number[]>(booking?.attendees ?? [])
  const [notes, setNotes] = useState(booking?.notes ?? '')
  const [repeat, setRepeat] = useState(false)
  const [weekdays, setWeekdays] = useState<number[]>(() => [isoWeekday(date)])
  const [until, setUntil] = useState(() => addDays(date, 28))
  const [errors, setErrors] = useState<Record<string, string>>({})

  const chosen = resources?.find((r) => r.id === resource)
  const needsApproval = !!chosen?.needs_approval && me.role !== 'admin'
  const slots = Array.from({ length: Math.max(0, (closes - opens) / 15 + 1) }, (_, i) => timeOf(opens + i * 15))
  const startOptions = slots.slice(0, -1)
  const endOptions = slots.filter((s) => minutesOf(s) > minutesOf(start))

  const payload = (extra: Record<string, unknown> = {}) => ({
    resource,
    title: title.trim() || '…',
    start: officeMoment(tz, date, start),
    end: officeMoment(tz, date, end),
    attendees: attendees.filter((a) => a !== me.id),
    notes,
    repeat: repeat && !booking ? { weekdays, until } : null,
    ...extra,
  })

  // Which dates are free, checked as you type (also shows a clash before saving).
  const checkKey = useDebouncedValue(JSON.stringify({ resource, date, start, end, repeat: repeat && !booking, weekdays, until }), 300)
  const check = useQuery({
    queryKey: [...BOOKINGS_KEY, 'check', checkKey, booking?.id ?? null],
    queryFn: async () => (await api.post<{ occurrences: Occurrence[] }>('/bookings/check/', payload({ booking: booking?.id }))).data.occurrences,
    enabled: !!resource && minutesOf(end) > minutesOf(start),
    retry: false,
  })
  const occurrences = check.data ?? []
  const bad = occurrences.filter((o) => o.problem)
  const good = occurrences.length - bad.length

  const save = useMutation({
    mutationFn: async () => {
      if (booking) return (await api.patch<Booking>(`/bookings/${booking.id}/`, payload())).data
      return (await api.post<{ bookings: Booking[] }>('/bookings/', payload({ skip_conflicts: repeat && bad.length > 0 }))).data
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: BOOKINGS_KEY })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      const created = 'bookings' in data ? data.bookings : [data]
      const pending = created.some((b) => b.status === 'pending')
      toast.success(
        booking ? t('bookings.saved') : pending ? t('bookings.requested') : t('bookings.booked', { count: created.length }),
      )
      onClose()
    },
    onError: (e) => {
      const info = apiError(e)
      setErrors(info.fields)
      void check.refetch()
      toast.error(Object.values(info.fields)[0] ?? info.message)
    },
  })

  const toggleDay = (d: number) => setWeekdays((w) => (w.includes(d) ? (w.length > 1 ? w.filter((x) => x !== d) : w) : [...w, d].sort()))
  const canSave = !!resource && !!title.trim() && minutesOf(end) > minutesOf(start) && !save.isPending && (!repeat || good > 0)

  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={booking ? t('bookings.edit') : t('bookings.new')}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => save.mutate()} disabled={!canSave}>
            {save.isPending && <Loader2 className="size-4 animate-spin" />}
            {booking
              ? t('common.save')
              : repeat && !occurrences.length
                ? t('bookings.book')
                : repeat && bad.length
                ? t('bookings.bookSkipping', { count: good, skipped: bad.length })
                : needsApproval
                  ? t('bookings.request')
                  : repeat
                    ? t('bookings.bookDates', { count: good })
                    : t('bookings.book')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <FormField id="bk-resource" label={t('bookings.resource')} error={errors.resource}>
          <SimpleSelect
            id="bk-resource"
            value={resource ? String(resource) : ''}
            onChange={(v) => setResource(Number(v))}
            options={[
              ...(resource ? [] : [{ value: '', label: t('bookings.chooseResource') }]),
              ...(resources ?? []).map((r) => ({ value: String(r.id), label: r.capacity ? `${r.name} (${t('resources.seats', { count: r.capacity })})` : r.name })),
            ]}
          />
        </FormField>
        {needsApproval && (
          <p className="flex items-start gap-2 rounded-md bg-amber-50 p-2.5 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
            <Info className="mt-0.5 size-4 shrink-0" />
            {t('bookings.needsApprovalHint')}
          </p>
        )}
        <FormField id="bk-title" label={t('bookings.title')} error={errors.title}>
          <Input id="bk-title" value={title} dir="auto" maxLength={150} onChange={(e) => setTitle(e.target.value)} placeholder={t('bookings.titlePlaceholder')} />
        </FormField>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <FormField id="bk-date" label={t('bookings.date')} error={errors.date} className="col-span-2 sm:col-span-1">
            <Input id="bk-date" type="date" value={date} min={todayInOffice(tz)} onChange={(e) => e.target.value && setDate(e.target.value)} className="font-latin" />
          </FormField>
          <FormField id="bk-start" label={t('bookings.start')} error={errors.start}>
            <SimpleSelect
              id="bk-start"
              value={start}
              onChange={(v) => {
                setStart(v)
                if (minutesOf(end) <= minutesOf(v)) setEnd(timeOf(Math.min(minutesOf(v) + 60, closes)))
              }}
              options={startOptions.map((s) => ({ value: s, label: fmt.clock(s) }))}
            />
          </FormField>
          <FormField id="bk-end" label={t('bookings.end')} error={errors.end}>
            <SimpleSelect id="bk-end" value={end} onChange={setEnd} options={endOptions.map((s) => ({ value: s, label: fmt.clock(s) }))} />
          </FormField>
        </div>

        {!booking && (
          <div className="grid gap-3 rounded-md border p-3">
            <label className="flex items-center gap-2 text-sm font-medium">
              <Checkbox checked={repeat} onCheckedChange={(v) => setRepeat(!!v)} />
              {t('bookings.repeatWeekly')}
            </label>
            {repeat && (
              <>
                <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('bookings.onDays')}>
                  {[0, 1, 2, 3, 4, 5, 6].map((d) => (
                    <button
                      key={d}
                      type="button"
                      aria-pressed={weekdays.includes(d)}
                      onClick={() => toggleDay(d)}
                      className={cn(
                        'rounded-full border px-3 py-1 text-xs',
                        weekdays.includes(d) ? 'border-primary bg-primary text-primary-foreground' : 'hover:bg-muted',
                      )}
                    >
                      {weekdayName(d, i18n.language === 'ur' ? 'ur-PK' : 'en-GB', 'short')}
                    </button>
                  ))}
                </div>
                <FormField id="bk-until" label={t('bookings.until')} error={errors.repeat}>
                  <Input id="bk-until" type="date" value={until} min={addDays(date, 1)} onChange={(e) => e.target.value && setUntil(e.target.value)} className="font-latin sm:w-48" />
                </FormField>
              </>
            )}
          </div>
        )}

        <Availability occurrences={occurrences} loading={check.isFetching && !check.data} repeat={repeat && !booking} />

        <FormField id="bk-attendees" label={t('bookings.attendees')} hint={t('bookings.attendeesHint')}>
          <PeoplePicker
            id="bk-attendees"
            value={attendees}
            onChange={setAttendees}
            people={(users ?? []).filter((u) => u.id !== me.id)}
            placeholder={t('bookings.pickAttendees')}
          />
        </FormField>
        <FormField id="bk-notes" label={t('bookings.notes')}>
          <Textarea id="bk-notes" value={notes} dir="auto" maxLength={2000} onChange={(e) => setNotes(e.target.value)} className="min-h-16" />
        </FormField>
      </div>
    </FormDialog>
  )
}

/** Free or taken, per date: one line for a single booking, a list for a weekly series. */
function Availability({ occurrences, loading, repeat }: { occurrences: Occurrence[]; loading: boolean; repeat: boolean }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  if (loading) return <p className="text-sm text-muted-foreground">{t('bookings.checking')}</p>
  if (!occurrences.length) return null
  if (!repeat) {
    const o = occurrences[0]
    return o.problem ? (
      <p className="flex items-start gap-2 text-sm text-destructive" role="status">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        {o.message}
      </p>
    ) : (
      <p className="flex items-center gap-2 text-sm text-success" role="status">
        <CheckCircle2 className="size-4" />
        {t('bookings.free')}
      </p>
    )
  }
  const bad = occurrences.filter((o) => o.problem)
  return (
    <div className="grid gap-1.5" role="status">
      <p className="text-sm font-medium">
        {bad.length ? t('bookings.someTaken', { count: bad.length, total: occurrences.length }) : t('bookings.allFree', { count: occurrences.length })}
      </p>
      <ul className="max-h-40 overflow-y-auto rounded-md border text-sm">
        {occurrences.map((o) => (
          <li key={o.start} className={cn('flex items-center gap-2 border-b px-2.5 py-1.5 last:border-0', o.problem && 'bg-destructive/5')}>
            {o.problem ? <AlertTriangle className="size-3.5 shrink-0 text-destructive" /> : <CheckCircle2 className="size-3.5 shrink-0 text-success" />}
            <span className="w-28 shrink-0 font-latin">{fmt.date(o.start)}</span>
            <span className={cn('min-w-0 flex-1 truncate', o.problem ? 'text-destructive' : 'text-muted-foreground')}>
              {o.problem ? `${o.message} — ${t('bookings.willSkip')}` : t('bookings.freeShort')}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
