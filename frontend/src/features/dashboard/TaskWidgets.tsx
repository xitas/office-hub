import { BarChart3, CheckSquare, Users } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { EmptyState, UserAvatar } from '@/components/common'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { DueLabel, PriorityBadge } from '@/features/tasks/TaskBits'
import { DoneButton } from '@/features/tasks/TaskList'
import { useFormat } from '@/lib/format'
import type { DashboardData, DashboardTask, TaskCompletion, WorkloadRow } from '@/lib/types'
import { cn } from '@/lib/utils'

function Widget({ title, icon: Icon, action, children, className }: { title: string; icon: typeof Users; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center gap-2">
        <Icon className="size-4 text-muted-foreground" />
        <CardTitle className="flex-1 text-sm font-medium">{title}</CardTitle>
        {action}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

const TABS = ['today', 'overdue', 'upcoming'] as const
type Tab = (typeof TABS)[number]

/** My tasks: due today, overdue and the next 7 days, with one-click complete. */
export function MyTasksWidget({ data, loading, className }: { data: DashboardData | undefined; loading: boolean; className?: string }) {
  const { t } = useTranslation()
  const lists: Record<Tab, DashboardTask[] | null | undefined> = {
    today: data?.tasks_today,
    overdue: data?.overdue,
    upcoming: data?.upcoming_deadlines,
  }
  // Start on the tab that needs attention most.
  const [tab, setTab] = useState<Tab | null>(null)
  const active: Tab = tab ?? (lists.overdue?.length ? 'overdue' : lists.today?.length ? 'today' : 'upcoming')
  if (!loading && data?.tasks_today === null) return null
  const items = lists[active] ?? []

  return (
    <Widget
      title={t('dashboard.myTasks')}
      icon={CheckSquare}
      className={className}
      action={
        <Link to="/tasks" className="text-xs text-primary hover:underline">
          {t('dashboard.allTasks')}
        </Link>
      }
    >
      <div role="tablist" aria-label={t('dashboard.myTasks')} className="mb-3 flex gap-1 rounded-lg bg-muted p-1">
        {TABS.map((key) => {
          const count = lists[key]?.length ?? 0
          return (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={active === key}
              onClick={() => setTab(key)}
              className={cn(
                'flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors',
                active === key ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {t(`dashboard.taskTabs.${key}`)}
              <span className={cn('rounded-full px-1.5 font-latin', key === 'overdue' && count ? 'bg-destructive/15 text-destructive' : 'bg-muted-foreground/15')}>
                {count}
              </span>
            </button>
          )
        })}
      </div>
      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-9" />
          <Skeleton className="h-9" />
        </div>
      ) : !items.length ? (
        <EmptyState icon={CheckSquare} title={t(`dashboard.taskEmpty.${active}`)} className="py-4" />
      ) : (
        <ul className="grid grid-cols-1 gap-1">
          {items.map((task) => (
            <li key={task.id} className="flex items-center gap-2 rounded-md py-1 pe-1 hover:bg-muted/40">
              <DoneButton task={task} />
              <Link to={task.url ?? `/tasks/${task.id}`} className="min-w-0 flex-1 truncate text-sm hover:text-primary">
                {task.title}
              </Link>
              <PriorityBadge priority={task.priority} className="hidden sm:inline-flex" />
              <DueLabel task={task} className="shrink-0 text-xs" />
            </li>
          ))}
        </ul>
      )}
    </Widget>
  )
}

/** Open tasks per person (managers: their department, admins: everyone), most overdue first. */
export function TeamWorkloadWidget({ rows, loading, className }: { rows: WorkloadRow[] | null | undefined; loading: boolean; className?: string }) {
  const { t } = useTranslation()
  if (!loading && rows === null) return null
  const max = Math.max(1, ...(rows ?? []).map((r) => r.open))
  return (
    <Widget title={t('dashboard.teamWorkload')} icon={Users} className={className}>
      {loading || !rows ? (
        <Skeleton className="h-32" />
      ) : !rows.length ? (
        <EmptyState icon={Users} title={t('dashboard.emptyList')} className="py-4" />
      ) : (
        <ul className="grid grid-cols-1 gap-2.5" aria-label={t('dashboard.teamWorkload')}>
          {rows.slice(0, 8).map((r) => (
            <li key={r.user_id} className="grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)_auto] items-center gap-3 text-sm">
              <Link to={`/team?user=${r.user_id}`} className="flex min-w-0 items-center gap-2 hover:text-primary">
                <UserAvatar name={r.name} src={r.avatar} className="size-6" />
                <bdi className="truncate">{r.name}</bdi>
              </Link>
              <span className="flex h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
                <span className="h-full bg-destructive/70" style={{ width: `${(r.overdue / max) * 100}%` }} />
                <span className="h-full bg-primary/60" style={{ width: `${((r.open - r.overdue) / max) * 100}%` }} />
              </span>
              <span className="text-end text-xs whitespace-nowrap">
                <span className="font-medium font-latin">{r.open}</span> <span className="text-muted-foreground">{t('dashboard.open')}</span>
                {r.overdue > 0 && (
                  <span className="text-destructive">
                    {' · '}
                    <span className="font-latin">{r.overdue}</span> {t('dashboard.overdueShort')}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Widget>
  )
}

/** This week: tasks completed vs created, per day. */
export function CompletionWidget({ data, loading, className }: { data: TaskCompletion | null | undefined; loading: boolean; className?: string }) {
  const { t, i18n } = useTranslation()
  const fmt = useFormat()
  if (!loading && data === null) return null
  const locale = i18n.language === 'ur' ? 'ur-PK' : 'en-PK'
  const max = Math.max(1, ...(data?.days ?? []).flatMap((d) => [d.done, d.created]))
  return (
    <Widget title={t('dashboard.completion')} icon={BarChart3} className={className}>
      {loading || !data ? (
        <Skeleton className="h-32" />
      ) : (
        <div className="grid gap-3">
          <p className="text-sm">
            <span className="text-2xl font-semibold text-success font-latin">{fmt.number(data.done)}</span>{' '}
            <span className="text-muted-foreground">{t('dashboard.completionDone')}</span>
            <span className="mx-2 text-muted-foreground">·</span>
            <span className="text-2xl font-semibold font-latin">{fmt.number(data.created)}</span>{' '}
            <span className="text-muted-foreground">{t('dashboard.completionCreated')}</span>
          </p>
          <ol className="grid h-24 grid-cols-7 items-end gap-1.5" aria-label={t('dashboard.completion')}>
            {data.days.map((d) => {
              const label = new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' }).format(new Date(`${d.date}T12:00:00Z`))
              return (
                <li key={d.date} className="flex h-full flex-col items-center justify-end gap-1" title={`${label}: ${t('dashboard.completionDay', { done: d.done, created: d.created })}`}>
                  <div className="flex h-full w-full items-end justify-center gap-0.5">
                    <span className="w-2 rounded-t bg-success" style={{ height: `${(d.done / max) * 100}%` }} />
                    <span className="w-2 rounded-t bg-primary/40" style={{ height: `${(d.created / max) * 100}%` }} />
                  </div>
                  <span className="text-[10px] text-muted-foreground">{label}</span>
                </li>
              )
            })}
          </ol>
          <div className="flex gap-4 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <span className="size-2 rounded-sm bg-success" />
              {t('dashboard.completionDone')}
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="size-2 rounded-sm bg-primary/40" />
              {t('dashboard.completionCreated')}
            </span>
          </div>
        </div>
      )}
    </Widget>
  )
}
