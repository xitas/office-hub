import { CalendarCheck, CalendarDays, Check, Stamp, Users, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { EmptyState, ErrorState, PageHeader } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useMe } from '@/lib/auth'
import { useApprovals, useMyBookings, type Booking } from '@/lib/bookings'
import { usePermission } from '@/lib/permissions'
import { BookingDetails, StatusBadge } from './BookingDetails'
import { useBookingActions, useWhen } from './hooks'

type Tab = 'upcoming' | 'past' | 'approvals'

/** My bookings (made by me or with me): upcoming and past; requests to approve for managers and admins. */
export function MyBookingsPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const canApprove = usePermission('bookings.approve')
  const requested = params.get('tab') as Tab | null
  const tab: Tab = requested === 'past' || (requested === 'approvals' && canApprove) ? requested : 'upcoming'
  const mine = useMyBookings(tab === 'past' ? 'past' : 'upcoming')
  const approvals = useApprovals(canApprove)
  const list = tab === 'approvals' ? approvals : mine
  const [opened, setOpened] = useState<Booking | null>(null)

  return (
    <>
      <PageHeader
        title={t('bookings.mine')}
        subtitle={t('bookings.mineSubtitle')}
        actions={
          <Button variant="outline" nativeButton={false} render={<Link to="/bookings" />}>
            <CalendarDays className="size-4" />
            {t('bookings.pageTitle')}
          </Button>
        }
      />
      <Tabs value={tab} onValueChange={(v) => setParams(v === 'upcoming' ? {} : { tab: String(v) }, { replace: true })} className="mb-4">
        <TabsList>
          <TabsTrigger value="upcoming">{t('bookings.upcoming')}</TabsTrigger>
          <TabsTrigger value="past">{t('bookings.past')}</TabsTrigger>
          {canApprove && (
            <TabsTrigger value="approvals">
              {t('bookings.approvals')}
              {!!approvals.data?.length && (
                <Badge variant="secondary" className="ms-1 font-latin">
                  {approvals.data.length}
                </Badge>
              )}
            </TabsTrigger>
          )}
        </TabsList>
      </Tabs>
      {list.isError ? (
        <ErrorState onRetry={() => void list.refetch()} />
      ) : list.isLoading ? (
        <div className="grid gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      ) : !list.data?.length ? (
        <EmptyState
          icon={tab === 'approvals' ? Stamp : CalendarCheck}
          title={t(tab === 'approvals' ? 'bookings.noApprovals' : tab === 'past' ? 'bookings.noPast' : 'bookings.noUpcoming')}
          className="py-16"
        />
      ) : (
        <ul className="grid gap-3">
          {list.data.map((b) => (
            <BookingRow key={b.id} booking={b} approvals={tab === 'approvals'} onOpen={() => setOpened(b)} />
          ))}
        </ul>
      )}
      {opened && <BookingDetails booking={opened} onClose={() => setOpened(null)} />}
    </>
  )
}

function BookingRow({ booking: b, approvals, onOpen }: { booking: Booking; approvals: boolean; onOpen: () => void }) {
  const { t } = useTranslation()
  const me = useMe()
  const when = useWhen()
  const { decide, busy } = useBookingActions(b)
  return (
    <li>
      <Card className="gap-2 py-3">
        <CardContent className="flex flex-wrap items-center gap-3 px-4">
          <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-start">
            <span className="flex flex-wrap items-center gap-2">
              <bdi className="font-medium">{b.title}</bdi>
              <StatusBadge status={b.status} />
            </span>
            <span className="mt-0.5 block text-sm text-muted-foreground">
              <bdi dir="ltr" className="font-latin">{when(b)}</bdi> · <bdi>{b.resource_name}</bdi>
            </span>
            <span className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
              {b.booked_by !== me.id || approvals ? (
                <span>{t('bookings.bookedBy', { name: b.booked_by_name })}</span>
              ) : (
                b.attendee_details.length > 0 && (
                  <>
                    <Users className="size-3.5" />
                    {b.attendee_details.map((a) => a.full_name).join(', ')}
                  </>
                )
              )}
            </span>
          </button>
          {approvals && b.can_decide && (
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={busy} onClick={onOpen}>
                <X className="size-4" />
                {t('bookings.reject')}
              </Button>
              <Button size="sm" disabled={busy} onClick={() => decide.mutate({ approve: true })}>
                <Check className="size-4" />
                {t('bookings.approve')}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </li>
  )
}
