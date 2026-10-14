import { Ban, Check, Clock, MapPin, Pencil, Repeat, UserRound, Users, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FormDialog } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import type { Booking } from '@/lib/bookings'
import { BookingDialog } from './BookingDialog'
import { useBookingActions, useWhen } from './hooks'

export function StatusBadge({ status }: { status: Booking['status'] }) {
  const { t } = useTranslation()
  const tone = {
    confirmed: 'border-success/40 text-success',
    pending: 'border-amber-500/50 text-amber-700 dark:text-amber-300',
    rejected: 'border-destructive/40 text-destructive',
    cancelled: 'text-muted-foreground',
  }[status]
  return (
    <Badge variant="outline" className={`font-normal ${tone}`}>
      {t(`bookings.status.${status}`)}
    </Badge>
  )
}

/** One booking: when, where, who; edit or cancel (booker, admins), approve or reject (approvers). */
export function BookingDetails({ booking, onClose }: { booking: Booking; onClose: () => void }) {
  const { t } = useTranslation()
  const when = useWhen()
  const [editing, setEditing] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const { askCancel, decide, busy } = useBookingActions(booking, onClose)

  if (editing) return <BookingDialog booking={booking} onClose={onClose} />
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={booking.title}
      footer={
        rejecting ? (
          <>
            <Button variant="outline" onClick={() => setRejecting(false)}>
              {t('common.cancel')}
            </Button>
            <Button variant="destructive" disabled={busy} onClick={() => decide.mutate({ approve: false, reason })}>
              {t('bookings.reject')}
            </Button>
          </>
        ) : (
          <div className="flex w-full flex-wrap justify-end gap-2">
            {booking.can_decide && (
              <>
                <Button variant="outline" disabled={busy} onClick={() => setRejecting(true)}>
                  <X className="size-4" />
                  {t('bookings.reject')}
                </Button>
                <Button disabled={busy} onClick={() => decide.mutate({ approve: true })}>
                  <Check className="size-4" />
                  {t('bookings.approve')}
                </Button>
              </>
            )}
            {booking.can_edit && (
              <>
                {booking.is_series && (
                  <Button variant="outline" className="text-destructive" disabled={busy} onClick={() => void askCancel(true)}>
                    <Ban className="size-4" />
                    {t('bookings.cancelFollowing')}
                  </Button>
                )}
                <Button variant="outline" className="text-destructive" disabled={busy} onClick={() => void askCancel(false)}>
                  <Ban className="size-4" />
                  {booking.is_series ? t('bookings.cancelThis') : t('bookings.cancelBooking')}
                </Button>
                <Button variant="outline" onClick={() => setEditing(true)}>
                  <Pencil className="size-4" />
                  {t('common.edit')}
                </Button>
              </>
            )}
          </div>
        )
      }
    >
      <div className="grid gap-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={booking.status} />
          {booking.is_series && (
            <Badge variant="outline" className="gap-1 font-normal">
              <Repeat className="size-3" />
              {t('bookings.series')}
            </Badge>
          )}
        </div>
        <p className="flex items-center gap-2">
          <MapPin className="size-4 text-muted-foreground" />
          <bdi className="font-medium">{booking.resource_name}</bdi>
        </p>
        <p className="flex items-center gap-2">
          <Clock className="size-4 text-muted-foreground" />
          <bdi dir="ltr" className="font-latin">{when(booking)}</bdi>
        </p>
        <p className="flex items-center gap-2">
          <UserRound className="size-4 text-muted-foreground" />
          {t('bookings.bookedBy', { name: booking.booked_by_name })}
        </p>
        {booking.attendee_details.length > 0 && (
          <p className="flex items-start gap-2">
            <Users className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            <span>{booking.attendee_details.map((a) => a.full_name).join(', ')}</span>
          </p>
        )}
        {booking.notes && <p className="whitespace-pre-wrap rounded-md bg-muted/50 p-2.5 [unicode-bidi:plaintext]">{booking.notes}</p>}
        {booking.status === 'pending' && !booking.can_decide && <p className="text-muted-foreground">{t('bookings.waitingApproval')}</p>}
        {booking.decision_reason && (
          <p className="text-muted-foreground">{t('bookings.reason', { reason: booking.decision_reason })}</p>
        )}
        {rejecting && (
          <div className="grid gap-1.5">
            <label htmlFor="bk-reason" className="font-medium">
              {t('bookings.rejectReason')}
            </label>
            <Textarea id="bk-reason" value={reason} dir="auto" maxLength={300} onChange={(e) => setReason(e.target.value)} autoFocus />
          </div>
        )}
      </div>
    </FormDialog>
  )
}
