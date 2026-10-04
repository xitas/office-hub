import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, CheckCheck } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { EmptyState } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { api } from '@/lib/api'
import { useFormat } from '@/lib/format'
import type { AppNotification, Paginated } from '@/lib/types'
import { cn } from '@/lib/utils'
import { UNREAD_COUNT_KEY } from '@/lib/ws'

// eslint-disable-next-line react-refresh/only-export-components
export function useUnreadCount() {
  const { data } = useQuery({
    queryKey: UNREAD_COUNT_KEY,
    queryFn: async () => (await api.get<{ count: number }>('/notifications/unread-count/')).data,
    staleTime: 60_000,
  })
  return data?.count ?? 0
}

// eslint-disable-next-line react-refresh/only-export-components
export function useNotificationActions() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['notifications'] })
    void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
  }
  const markRead = useMutation({
    mutationFn: (id: number) => api.post(`/notifications/${id}/read/`),
    onSuccess: invalidate,
  })
  const markAllRead = useMutation({
    mutationFn: () => api.post('/notifications/read-all/'),
    onSuccess: invalidate,
  })
  return { markRead, markAllRead }
}

export function NotificationItem({ n, onOpen }: { n: AppNotification; onOpen: (n: AppNotification) => void }) {
  const fmt = useFormat()
  return (
    <button
      type="button"
      onClick={() => onOpen(n)}
      className={cn(
        'flex w-full gap-3 rounded-md px-3 py-2.5 text-start transition-colors hover:bg-muted',
        !n.is_read && 'bg-primary/5',
      )}
    >
      <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', n.is_read ? 'bg-transparent' : 'bg-primary')} />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium">{n.title}</span>
        {n.body && <span className="line-clamp-2 block text-xs text-muted-foreground">{n.body}</span>}
        <span className="mt-0.5 block text-xs text-muted-foreground">{fmt.relative(n.created_at)}</span>
      </span>
    </button>
  )
}

export function NotificationBell() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const unread = useUnreadCount()
  const { markRead, markAllRead } = useNotificationActions()

  const { data } = useQuery({
    queryKey: ['notifications', 'list', 'recent'],
    queryFn: async () => (await api.get<Paginated<AppNotification>>('/notifications/', { params: { page_size: 8 } })).data,
    enabled: open,
  })

  const openNotification = (n: AppNotification) => {
    if (!n.is_read) markRead.mutate(n.id)
    setOpen(false)
    if (n.link) navigate(n.link)
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={<Button variant="ghost" size="icon" className="relative" aria-label={t('notifications.title')} />}
      >
        <Bell className="size-5" />
        {unread > 0 && (
          <span className="absolute -end-0.5 -top-0.5 min-w-4 rounded-full bg-destructive px-1 text-center text-[10px] leading-4 text-white font-latin">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(22rem,calc(100vw-2rem))] p-0">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <span className="text-sm font-semibold">{t('notifications.title')}</span>
          <Button variant="ghost" size="sm" disabled={unread === 0} onClick={() => markAllRead.mutate()}>
            <CheckCheck className="size-4" />
            {t('notifications.markAllRead')}
          </Button>
        </div>
        <div className="max-h-96 overflow-y-auto p-1">
          {data?.results.length ? (
            data.results.map((n) => <NotificationItem key={n.id} n={n} onOpen={openNotification} />)
          ) : (
            <EmptyState icon={Bell} title={t('notifications.empty')} />
          )}
        </div>
        <div className="border-t p-1">
          <Button variant="ghost" size="sm" className="w-full" nativeButton={false} render={<Link to="/notifications" onClick={() => setOpen(false)} />}>
            {t('notifications.viewAll')}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
