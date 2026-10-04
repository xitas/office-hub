import { useQuery } from '@tanstack/react-query'
import { Bell, CheckCheck } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { EmptyState, ErrorState, PageHeader, Pagination } from '@/components/common'
import { NotificationItem, useNotificationActions, useUnreadCount } from '@/components/layout/NotificationBell'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { api } from '@/lib/api'
import type { AppNotification, Paginated } from '@/lib/types'

export function NotificationsPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [page, setPage] = useState(1)
  const unread = useUnreadCount()
  const { markRead, markAllRead } = useNotificationActions()

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['notifications', 'list', { unreadOnly, page }],
    queryFn: async () =>
      (
        await api.get<Paginated<AppNotification>>('/notifications/', {
          params: { page, is_read: unreadOnly ? false : undefined },
        })
      ).data,
  })

  const open = (n: AppNotification) => {
    if (!n.is_read) markRead.mutate(n.id)
    if (n.link) navigate(n.link)
  }

  return (
    <>
      <PageHeader
        title={t('notifications.title')}
        actions={
          <>
            <div className="flex items-center gap-2">
              <Switch
                id="unread-only"
                checked={unreadOnly}
                onCheckedChange={(v) => {
                  setUnreadOnly(v)
                  setPage(1)
                }}
              />
              <Label htmlFor="unread-only">{t('notifications.unreadOnly')}</Label>
            </div>
            <Button variant="outline" size="sm" disabled={unread === 0} onClick={() => markAllRead.mutate()}>
              <CheckCheck className="size-4" />
              {t('notifications.markAllRead')}
            </Button>
          </>
        }
      />
      <Card>
        <CardContent className="p-2">
          {isError ? (
            <ErrorState onRetry={() => void refetch()} />
          ) : isLoading ? (
            <div className="space-y-2 p-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
          ) : !data?.results.length ? (
            <EmptyState icon={Bell} title={t('notifications.empty')} />
          ) : (
            data.results.map((n) => <NotificationItem key={n.id} n={n} onOpen={open} />)
          )}
        </CardContent>
      </Card>
      {data && <Pagination page={page} count={data.count} onPage={setPage} />}
    </>
  )
}
