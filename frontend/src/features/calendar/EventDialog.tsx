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
import { BOOKINGS_KEY, minutesOf, officeMoment, officeParts, timeOf, todayInOffice, useResources, type Occurrence } from '@/lib/bookings'
import { CALENDAR_KEY, useAllowedKinds, type OfficeEvent } from '@/lib/calendar'
import { useFormat } from '@/lib/format'
import { useDepartments, useUserOptions } from '@/lib/queries'
import { useDebouncedValue } from '@/lib/useDebouncedValue'

type Kind = OfficeEvent['kind']

export interface EventDraft {
  kind?: Kind
  date?: string
  start?: string // "HH:MM" office time
}

/** Add or change a meeting (attendees, optional room), an office event (audience) or a holiday (all day). */
export function EventDialog({ event, draft, onClose }: { event?: OfficeEvent; draft?: EventDraft; onClose: () => void }) {
  const { t } = useTranslation()
  const me = useMe()
  const fmt = useFormat()
  const tz = fmt.settings.timezone
  const queryClient = useQueryClient()
  const kinds = useAllowedKinds()
  const { data: users } = useUserOptions()
  const { data: departments } = useDepartments()
  const { data: resources } = useResources({ active: true })
  const rooms = (resources ?? []).filter((r) => r.type === 'room')
  const opens = minutesOf(fmt.settings.office_opens)
  const today = todayInOffice(tz)

  const timed = event && !event.all_day ? { s: officeParts(tz, event.start), e: officeParts(tz, event.end) } : null
  const [kind, setKind] = useState<Kind>(event?.kind ?? draft?.kind ?? 'meeting')
  const [title, setTitle] = useState(event?.title ?? '')
  const [allDay, setAllDay] = useState(event?.all_day ?? false)
  const [date, setDate] = useState(event?.start_date ?? timed?.s.date ?? draft?.date ?? today)
  const [endDate, setEndDate] = useState(event?.end_date ?? event?.start_date ?? draft?.date ?? today)
  // Today: the next quarter hour (not a time that has passed); other days: when the office opens.
  const [nowMinutes] = useState(() => minutesOf(officeParts(tz, new Date()).time))
  const firstDay = draft?.date ?? today
  const firstStart = draft?.start ?? timeOf(firstDay === today ? Math.min(Math.max(opens, Math.ceil((nowMinutes + 1) / 15) * 15), 23 * 60) : opens)
  const [start, setStart] = useState(timed?.s.time ?? firstStart)
  const [end, setEnd] = useState(timed?.e.time ?? timeOf(Math.min(minutesOf(firstStart) + 60, 24 * 60 - 15)))
  const [location, setLocation] = useState(event?.location ?? '')
  const [room, setRoom] = useState<number | null>(event?.room ?? null)
  const [attendees, setAttendees] = useState<number[]>(event?.attendees ?? [])
  const [audience, setAudience] = useState<OfficeEvent['audience']>(event?.audience ?? (me.role === 'admin' ? 'everyone' : 'departments'))
  const [chosen, setChosen] = useState<number[]>(event?.departments ?? (me.department ? [me.department] : []))
  const [description, setDescription] = useState(event?.description ?? '')
  const [errors, setErrors] = useState<Record<string, string>>({})

  const isAllDay = kind === 'holiday' || (kind === 'event' && allDay)
  const steps = Array.from({ length: 96 }, (_, i) => timeOf(i * 15))
  const startIso = officeMoment(tz, date, start)
  const endIso = officeMoment(tz, date, end)

  // Is the room free then? (Same check as the booking form; the meeting's own booking doesn't count.)
  const checkKey = useDebouncedValue(JSON.stringify({ room, date, start, end }), 300)
  const roomCheck = useQuery({
    queryKey: [...BOOKINGS_KEY, 'check', 'meeting', checkKey, event?.id ?? null],
    queryFn: async () =>
      (await api.post<{ occurrences: Occurrence[] }>('/bookings/check/', {
        resource: room, title: title || '…', start: startIso, end: endIso, booking: event?.room === room ? event?.booking : undefined,
      })).data.occurrences[0],
    enabled: kind === 'meeting' && !!room && minutesOf(end) > minutesOf(start),
    retry: false,
  })

  const payload = () => {
    const body: Record<string, unknown> = { kind, title, description, location }
    if (isAllDay) Object.assign(body, { all_day: true, start_date: date, end_date: endDate < date ? date : endDate })
    else Object.assign(body, { all_day: false, start: startIso, end: endIso })
    if (kind === 'meeting') Object.assign(body, { attendees: attendees.filter((a) => a !== me.id), room })
    if (kind === 'event') Object.assign(body, { audience, departments: audience === 'departments' ? chosen : [] })
    return body
  }

  const save = useMutation({
    mutationFn: async () =>
      event ? (await api.patch<OfficeEvent>(`/events/${event.id}/`, payload())).data : (await api.post<OfficeEvent>('/events/', payload())).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CALENDAR_KEY })
      void queryClient.invalidateQueries({ queryKey: BOOKINGS_KEY })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      toast.success(event ? t('calendar.saved') : t(`calendar.added.${kind}`))
      onClose()
    },
    onError: (e) => {
      const info = apiError(e)
      setErrors(info.fields)
      toast.error(Object.values(info.fields)[0] ?? info.message)
    },
  })

  const canSave = !!title.trim() && (isAllDay || minutesOf(end) > minutesOf(start)) && !save.isPending
  const roomInfo = rooms.find((r) => r.id === room)

  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={event ? t(`calendar.edit.${kind}`) : t(`calendar.new.${kind}`)}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => save.mutate()} disabled={!canSave}>
            {save.isPending && <Loader2 className="size-4 animate-spin" />}
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {!event && kinds.length > 1 && (
          <div className="flex rounded-lg bg-muted p-0.5" role="radiogroup" aria-label={t('calendar.kind')}>
            {kinds.map((k) => (
              <button
                key={k}
                type="button"
                role="radio"
                aria-checked={kind === k}
                onClick={() => setKind(k)}
                className={kind === k ? 'flex-1 rounded-md bg-card px-2.5 py-1 text-sm font-medium shadow-sm' : 'flex-1 rounded-md px-2.5 py-1 text-sm text-muted-foreground hover:text-foreground'}
              >
                {t(`calendar.kinds.${k}`)}
              </button>
            ))}
          </div>
        )}
        <FormField id="ev-title" label={t('calendar.title')} error={errors.title}>
          <Input id="ev-title" value={title} dir="auto" maxLength={150} onChange={(e) => setTitle(e.target.value)} placeholder={t(`calendar.titlePlaceholder.${kind}`)} />
        </FormField>
        {kind === 'event' && (
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={allDay} onCheckedChange={(v) => setAllDay(!!v)} />
            {t('calendar.allDay')}
          </label>
        )}
        {isAllDay ? (
          <div className="grid grid-cols-2 gap-3">
            <FormField id="ev-date" label={t('calendar.firstDay')} error={errors.start_date}>
              <Input id="ev-date" type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} className="font-latin" />
            </FormField>
            <FormField id="ev-end-date" label={t('calendar.lastDay')} error={errors.end_date}>
              <Input id="ev-end-date" type="date" value={endDate < date ? date : endDate} min={date} onChange={(e) => e.target.value && setEndDate(e.target.value)} className="font-latin" />
            </FormField>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <FormField id="ev-date" label={t('calendar.date')} error={errors.start} className="col-span-2 sm:col-span-1">
              <Input id="ev-date" type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} className="font-latin" />
            </FormField>
            <FormField id="ev-start" label={t('calendar.from')}>
              <SimpleSelect
                id="ev-start"
                value={start}
                onChange={(v) => {
                  setStart(v)
                  if (minutesOf(end) <= minutesOf(v)) setEnd(timeOf(Math.min(minutesOf(v) + 60, 24 * 60 - 15)))
                }}
                options={steps.slice(0, -1).map((s) => ({ value: s, label: fmt.clock(s) }))}
              />
            </FormField>
            <FormField id="ev-end" label={t('calendar.to')} error={errors.end}>
              <SimpleSelect id="ev-end" value={end} onChange={setEnd} options={steps.filter((s) => minutesOf(s) > minutesOf(start)).map((s) => ({ value: s, label: fmt.clock(s) }))} />
            </FormField>
          </div>
        )}

        {kind === 'meeting' && (
          <>
            <FormField id="ev-room" label={t('calendar.room')} error={errors.room} hint={t('calendar.roomHint')}>
              <SimpleSelect
                id="ev-room"
                value={room ? String(room) : ''}
                onChange={(v) => setRoom(v ? Number(v) : null)}
                options={[{ value: '', label: t('calendar.noRoom') }, ...rooms.map((r) => ({ value: String(r.id), label: r.capacity ? `${r.name} (${t('resources.seats', { count: r.capacity })})` : r.name }))]}
              />
            </FormField>
            {room && roomInfo?.needs_approval && me.role !== 'admin' && (
              <p className="flex items-start gap-2 rounded-md bg-amber-50 p-2.5 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
                <Info className="mt-0.5 size-4 shrink-0" />
                {t('bookings.needsApprovalHint')}
              </p>
            )}
            {room && roomCheck.data && (
              roomCheck.data.problem ? (
                <p className="flex items-start gap-2 text-sm text-destructive" role="status">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                  {roomCheck.data.message}
                </p>
              ) : (
                <p className="flex items-center gap-2 text-sm text-success" role="status">
                  <CheckCircle2 className="size-4" />
                  {t('calendar.roomFree')}
                </p>
              )
            )}
          </>
        )}
        {(kind !== 'meeting' || !room) && (
          <FormField id="ev-location" label={t('calendar.location')}>
            <Input id="ev-location" value={location} dir="auto" maxLength={150} onChange={(e) => setLocation(e.target.value)} />
          </FormField>
        )}
        {kind === 'meeting' && (
          <FormField id="ev-attendees" label={t('calendar.attendees')} hint={t('calendar.attendeesHint')}>
            <PeoplePicker id="ev-attendees" value={attendees} onChange={setAttendees} people={(users ?? []).filter((u) => u.id !== me.id)} placeholder={t('bookings.pickAttendees')} />
          </FormField>
        )}
        {kind === 'event' &&
          (me.role === 'admin' ? (
            <FormField id="ev-audience" label={t('calendar.audience')} error={errors.departments}>
              <SimpleSelect
                id="ev-audience"
                value={audience}
                onChange={(v) => setAudience(v as OfficeEvent['audience'])}
                options={[
                  { value: 'everyone', label: t('calendar.audiences.everyone') },
                  { value: 'departments', label: t('calendar.audiences.departments') },
                ]}
              />
              {audience === 'departments' && (
                <div className="mt-1 grid gap-2 rounded-md border p-2.5 sm:grid-cols-2">
                  {(departments ?? []).map((d) => (
                    <label key={d.id} className="flex items-center gap-2 text-sm">
                      <Checkbox checked={chosen.includes(d.id)} onCheckedChange={(on) => setChosen((c) => (on ? [...c, d.id] : c.filter((x) => x !== d.id)))} />
                      <bdi>{d.name}</bdi>
                    </label>
                  ))}
                </div>
              )}
            </FormField>
          ) : (
            <div className="grid gap-1.5">
              <span className="text-sm font-medium">{t('calendar.audience')}</span>
              <p className="rounded-md bg-muted/60 px-3 py-2 text-sm">{t('calendar.forDepartment', { name: me.department_name ?? '' })}</p>
            </div>
          ))}
        <FormField id="ev-description" label={t('calendar.description')}>
          <Textarea id="ev-description" value={description} dir="auto" maxLength={4000} onChange={(e) => setDescription(e.target.value)} className="min-h-16" />
        </FormField>
      </div>
    </FormDialog>
  )
}
