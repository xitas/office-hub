import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api, apiError } from '@/lib/api'
import { BOOKINGS_KEY, officeParts, type Booking } from '@/lib/bookings'
import { useConfirm } from '@/lib/confirm'
import { useFormat } from '@/lib/format'

/** "Wed 15/10/2026 · 10:00–11:00" in the office time zone. */
export function useWhen() {
  const fmt = useFormat()
  // Office-clock times in the person's 12- or 24-hour clock, like the timeline and the booking form.
  const tz = fmt.settings.timezone
  return (b: Pick<Booking, 'start' | 'end'>) => `${fmt.date(b.start)} · ${fmt.clock(officeParts(tz, b.start).time)}–${fmt.clock(officeParts(tz, b.end).time)}`
}

export function useBookingActions(booking: Booking, onDone?: () => void) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const confirm = useConfirm()
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: BOOKINGS_KEY })
    void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
  }
  const cancel = useMutation({
    mutationFn: async (following: boolean) => (await api.post<{ cancelled: number[] }>(`/bookings/${booking.id}/cancel/`, { following })).data,
    onSuccess: (data) => {
      refresh()
      toast.success(t('bookings.cancelledToast', { count: data.cancelled.length }))
      onDone?.()
    },
    onError: (e) => toast.error(apiError(e).message),
  })
  const decide = useMutation({
    mutationFn: async ({ approve, reason }: { approve: boolean; reason?: string }) =>
      (await api.post<Booking>(`/bookings/${booking.id}/decide/`, { approve, reason: reason ?? '' })).data,
    onSuccess: (data) => {
      refresh()
      toast.success(data.status === 'confirmed' ? t('bookings.approvedToast') : t('bookings.rejectedToast'))
      onDone?.()
    },
    onError: (e) => toast.error(apiError(e).message),
  })
  const askCancel = async (following = false) => {
    const ok = await confirm({
      title: following ? t('bookings.cancelSeriesTitle') : t('bookings.cancelTitle'),
      description: t('bookings.cancelText', { title: booking.title }),
      confirmLabel: t('bookings.cancelConfirm'),
      cancelLabel: t('bookings.keep'),
      destructive: true,
    })
    if (ok) cancel.mutate(following)
  }
  return { askCancel, decide, busy: cancel.isPending || decide.isPending }
}

