import { useQuery } from '@tanstack/react-query'
import {
  AlarmClock,
  Bell,
  Building2,
  CalendarClock,
  CalendarDays,
  CheckSquare,
  DoorOpen,
  History,
  LogIn,
  MessagesSquare,
  Sparkles,
  Stamp,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorState, PageHeader } from '@/components/common'
import { QuickAdd } from '@/components/layout/QuickAdd'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { useFormat } from '@/lib/format'
import type { ActivityItem, DashboardData, DashboardListItem } from '@/lib/types'
import { cn } from '@/lib/utils'

function greetingKey(hour: number) {
  if (hour < 12) return 'dashboard.greetingMorning'
  if (hour < 17) return 'dashboard.greetingAfternoon'
  return 'dashboard.greetingEvening'
}

const LIST_WIDGETS: { key: keyof DashboardData; title: string; icon: LucideIcon; tone?: string }[] = [
  { key: 'tasks_today', title: 'dashboard.tasksToday', icon: CheckSquare },
  { key: 'overdue', title: 'dashboard.overdue', icon: AlarmClock, tone: 'text-destructive' },
  { key: 'upcoming_deadlines', title: 'dashboard.deadlines', icon: CalendarClock },
  { key: 'unread_messages', title: 'dashboard.unreadMessages', icon: MessagesSquare },
  { key: 'pending_approvals', title: 'dashboard.pendingApprovals', icon: Stamp },
  { key: 'meetings_today', title: 'dashboard.meetingsToday', icon: CalendarDays },
  { key: 'bookings_today', title: 'dashboard.bookingsToday', icon: DoorOpen },
]

export function DashboardPage() {
  const { t } = useTranslation()
  const me = useMe()
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: async () => (await api.get<DashboardData>('/dashboard/')).data,
    refetchInterval: 120_000,
  })

  const fmt = useFormat()
  const firstName = me.full_name.split(' ')[0]
  // Widgets whose module isn't released yet (value null) collapse into one compact card.
  const live = data ? LIST_WIDGETS.filter((w) => data[w.key] !== null) : []
  const upcoming = data ? LIST_WIDGETS.filter((w) => data[w.key] === null) : []

  return (
    <>
      <PageHeader
        title={t(greetingKey(fmt.currentHour()), { name: firstName })}
        subtitle={t('dashboard.subtitle')}
        actions={
          // The top bar has quick-add on larger screens; phones get it here.
          <div className="md:hidden">
            <QuickAdd />
          </div>
        }
      />

      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : (
        <div className="grid gap-6">
          <StatsRow data={data} loading={isLoading} />

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {live.map((w) => (
              <ListWidget
                key={w.key}
                title={t(w.title)}
                icon={w.icon}
                tone={w.tone}
                loading={isLoading}
                items={data?.[w.key] as DashboardListItem[] | null | undefined}
              />
            ))}
            <ActivityWidget items={data?.activity} loading={isLoading} className="md:col-span-2" />
            {upcoming.length > 0 && <ComingSoonWidget widgets={upcoming} className="md:col-span-2 xl:col-span-1" />}
          </div>
        </div>
      )}
    </>
  )
}

function StatsRow({ data, loading }: { data?: DashboardData; loading: boolean }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const stats: { label: string; value: number | null | undefined; icon: LucideIcon; to?: string }[] = [
    { label: t('dashboard.unreadNotifications'), value: data?.unread_notifications, icon: Bell, to: '/notifications' },
  ]
  if (data?.stats) {
    stats.push(
      { label: t('dashboard.activeUsers'), value: data.stats.active_users, icon: Users, to: '/team' },
      { label: t('dashboard.loggedInToday'), value: data.stats.logged_in_today, icon: LogIn },
    )
    if (data.stats.departments !== null)
      stats.push({ label: t('dashboard.departments'), value: data.stats.departments, icon: Building2 })
  }

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {loading
        ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[88px] rounded-xl" />)
        : stats.map((s) => {
            const body = (
              <Card className="h-full transition-colors hover:bg-muted/40">
                <CardContent className="flex items-center gap-3">
                  <div className="rounded-lg bg-primary/10 p-2 text-primary">
                    <s.icon className="size-5" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-2xl font-semibold font-latin">{fmt.number(s.value ?? 0)}</p>
                    <p className="truncate text-xs text-muted-foreground">{s.label}</p>
                  </div>
                </CardContent>
              </Card>
            )
            return s.to ? (
              <Link key={s.label} to={s.to} className="rounded-xl focus-visible:ring-2 focus-visible:ring-ring">
                {body}
              </Link>
            ) : (
              <div key={s.label}>{body}</div>
            )
          })}
    </div>
  )
}

function WidgetCard({
  title,
  icon: Icon,
  tone,
  count,
  children,
  className,
}: {
  title: string
  icon: LucideIcon
  tone?: string
  count?: number
  children: React.ReactNode
  className?: string
}) {
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center gap-2">
        <Icon className={cn('size-4 text-muted-foreground', tone)} />
        <CardTitle className="flex-1 text-sm font-medium">{title}</CardTitle>
        {count !== undefined && count > 0 && (
          <Badge variant="secondary" className="font-latin">
            {count}
          </Badge>
        )}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

function ListWidget({
  title,
  icon,
  tone,
  items,
  loading,
}: {
  title: string
  icon: LucideIcon
  tone?: string
  items: DashboardListItem[] | null | undefined
  loading: boolean
}) {
  const { t } = useTranslation()
  const fmt = useFormat()
  return (
    <WidgetCard title={title} icon={icon} tone={tone} count={items?.length}>
      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      ) : items === null || items === undefined ? (
        <EmptyState icon={icon} title={t('common.comingSoon')} hint={t('common.comingSoonHint')} className="py-4" />
      ) : items.length === 0 ? (
        <EmptyState icon={icon} title={t('dashboard.emptyList')} className="py-4" />
      ) : (
        <ul className="divide-y">
          {items.slice(0, 5).map((item) => (
            <li key={item.id}>
              <Link to={item.url ?? '#'} className="flex items-center gap-2 py-2 text-sm hover:text-primary">
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{item.title}</span>
                  {item.subtitle && <span className="block truncate text-xs text-muted-foreground">{item.subtitle}</span>}
                </span>
                {item.badge && <Badge variant="outline">{item.badge}</Badge>}
                {item.time && <span className="shrink-0 text-xs text-muted-foreground">{fmt.time(item.time)}</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </WidgetCard>
  )
}

function ComingSoonWidget({ widgets, className }: { widgets: typeof LIST_WIDGETS; className?: string }) {
  const { t } = useTranslation()
  return (
    <WidgetCard title={t('common.comingSoon')} icon={Sparkles} className={className}>
      <p className="mb-3 text-xs text-muted-foreground">{t('dashboard.comingSoonHint')}</p>
      <ul className="grid gap-2">
        {widgets.map((w) => (
          <li key={w.key} className="flex items-center gap-2 rounded-md bg-muted/60 px-2.5 py-1.5 text-sm text-muted-foreground">
            <w.icon className="size-4 shrink-0" />
            {t(w.title)}
          </li>
        ))}
      </ul>
    </WidgetCard>
  )
}

function ActivityWidget({
  items,
  loading,
  className,
}: {
  items: ActivityItem[] | null | undefined
  loading: boolean
  className?: string
}) {
  const { t } = useTranslation()
  const fmt = useFormat()
  return (
    <WidgetCard title={t('dashboard.activity')} icon={History} className={className}>
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
        </div>
      ) : !items?.length ? (
        <EmptyState icon={History} title={t('dashboard.noActivity')} className="py-4" />
      ) : (
        <ol className="relative space-y-4 border-s ps-4">
          {items.map((a) => {
            const verb = ['create', 'update', 'delete'].includes(a.action) ? a.action : 'other'
            return (
              <li key={a.id} className="relative">
                <span className="absolute -start-[21px] top-1.5 size-2 rounded-full bg-primary ring-4 ring-card" />
                <p className="text-sm">
                  {t(`dashboard.verb.${verb}`, {
                    actor: a.actor_name ?? t('dashboard.someone'),
                    object: a.object_repr || a.model_label || '',
                  })}
                </p>
                <p className="text-xs text-muted-foreground">
                  {a.model_label && <span className="capitalize">{a.model_label} · </span>}
                  {fmt.relative(a.timestamp)}
                </p>
              </li>
            )
          })}
        </ol>
      )}
    </WidgetCard>
  )
}
