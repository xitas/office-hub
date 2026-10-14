import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CalendarDays, Clock, DoorOpen, Loader2, MapPin, Pencil, Trash2, UserRound, Users } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { FormDialog } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api, apiError } from '@/lib/api'
import { BOOKINGS_KEY, officeParts } from '@/lib/bookings'
import { CALENDAR_KEY, TYPE_STYLES, useOfficeEvent, type OfficeEvent } from '@/lib/calendar'
import { useConfirm } from '@/lib/confirm'
import { useFormat } from '@/lib/format'
import { cn } from '@/lib/utils'
import { EventDialog } from './EventDialog'

/** When an item happens, in the office time zone: a day range for all-day items, else a time range. */
export function EventWhen({ event }: { event: Pick<OfficeEvent, 'all_day' | 'start' | 'end' | 'start_date' | 'end_date'> }) {
  const fmt = useFormat()
  const tz = fmt.settings.timezone
  if (event.all_day && event.start_date && event.end_date) {
    const first = fmt.date(`${event.start_date}T12:00:00`)
    return <bdi dir="ltr" className="font-latin">{event.start_date === event.end_date ? first : `${first} – ${fmt.date(`${event.end_date}T12:00:00`)}`}</bdi>
  }
  const s = officeParts(tz, event.start)
  const e = officeParts(tz, event.end)
  return (
    <bdi dir="ltr" className="font-latin">
      {fmt.date(event.start)} · {fmt.clock(s.time)}–{fmt.clock(e.time)}
    </bdi>
  )
}

/** One meeting, office event or holiday; the organizer or an admin edits or removes it. */
export function EventDetails({ id, onClose }: { id: number; onClose: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const confirm = useConfirm()
  const { data: event, isLoading, isError } = useOfficeEvent(id)
  const [editing, setEditing] = useState(false)
  const remove = useMutation({
    mutationFn: async () => api.delete(`/events/${id}/`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CALENDAR_KEY })
      void queryClient.invalidateQueries({ queryKey: BOOKINGS_KEY })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      toast.success(t('calendar.removed'))
      onClose()
    },
    onError: (e) => toast.error(apiError(e).message),
  })

  if (editing && event) return <EventDialog event={event} onClose={onClose} />
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={event?.title ?? t('calendar.loading')}
      footer={
        event?.can_edit && (
          <>
            <Button
              variant="outline"
              className="text-destructive"
              disabled={remove.isPending}
              onClick={async () => {
                const ok = await confirm({
                  title: t(`calendar.removeTitle.${event.kind}`),
                  description: event.kind === 'meeting' ? t('calendar.removeMeetingText') : t('calendar.removeText', { title: event.title }),
                  confirmLabel: t('calendar.remove'),
                  destructive: true,
                })
                if (ok) remove.mutate()
              }}
            >
              <Trash2 className="size-4" />
              {t('calendar.remove')}
            </Button>
            <Button variant="outline" onClick={() => setEditing(true)}>
              <Pencil className="size-4" />
              {t('common.edit')}
            </Button>
          </>
        )
      }
    >
      {isLoading ? (
        <Loader2 className="mx-auto size-6 animate-spin text-muted-foreground" />
      ) : isError || !event ? (
        <p className="text-sm text-muted-foreground">{t('calendar.notFound')}</p>
      ) : (
        <div className="grid gap-3 text-sm">
          <div>
            <Badge variant="outline" className={cn('font-normal', TYPE_STYLES[event.kind])}>
              {t(`calendar.kinds.${event.kind}`)}
            </Badge>
          </div>
          <p className="flex items-center gap-2">
            {event.all_day ? <CalendarDays className="size-4 text-muted-foreground" /> : <Clock className="size-4 text-muted-foreground" />}
            <EventWhen event={event} />
          </p>
          {event.room_name && (
            <p className="flex items-center gap-2">
              <DoorOpen className="size-4 text-muted-foreground" />
              <bdi className="font-medium">{event.room_name}</bdi>
              {event.room_status === 'pending' && (
                <Badge variant="outline" className="border-amber-500/50 font-normal text-amber-700 dark:text-amber-300">
                  {t('calendar.roomPending')}
                </Badge>
              )}
            </p>
          )}
          {event.location && (
            <p className="flex items-center gap-2">
              <MapPin className="size-4 text-muted-foreground" />
              <bdi>{event.location}</bdi>
            </p>
          )}
          {event.organizer_name && event.kind !== 'holiday' && (
            <p className="flex items-center gap-2">
              <UserRound className="size-4 text-muted-foreground" />
              {t('calendar.organizer', { name: event.organizer_name })}
            </p>
          )}
          {event.kind === 'meeting' && event.attendee_details.length > 0 && (
            <p className="flex items-start gap-2">
              <Users className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <span>{event.attendee_details.map((a) => a.full_name).join(', ')}</span>
            </p>
          )}
          {event.kind === 'event' && (
            <p className="text-muted-foreground">
              {event.audience === 'everyone' ? t('calendar.forEveryone') : t('calendar.forList', { names: event.department_names.join(', ') })}
            </p>
          )}
          {event.description && <p className="whitespace-pre-wrap rounded-md bg-muted/50 p-2.5 [unicode-bidi:plaintext]">{event.description}</p>}
        </div>
      )}
    </FormDialog>
  )
}
