import { Target } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useMe } from '@/lib/auth'
import { todayInOffice, weekStartOf } from '@/lib/bookings'
import { useFormat } from '@/lib/format'
import { GOAL_BAR, goalState, useWeekGoals } from '@/lib/planning'
import { cn } from '@/lib/utils'

/** This week's goals I can see (mine first). Loaded on its own, not part of /dashboard/. */
export function WeeklyGoalsCard({ className }: { className?: string }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const me = useMe()
  const today = todayInOffice(fmt.settings.timezone)
  const { data, isLoading } = useWeekGoals(weekStartOf(today, fmt.settings.week_start))
  const goals = [...(data?.goals ?? [])].sort((a, b) => Number(b.owner === me.id) - Number(a.owner === me.id) || Number(a.done) - Number(b.done))
  const done = goals.filter((g) => g.done).length
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center gap-2">
        <Target className="size-4 text-muted-foreground" />
        <CardTitle className="flex-1 text-sm font-medium">{t('planning.cardTitle')}</CardTitle>
        {goals.length > 0 && <span className="text-xs text-muted-foreground">{t('planning.doneOf', { done, total: goals.length })}</span>}
        <Link to="/planning" className="text-xs text-primary hover:underline">{t('planning.open')}</Link>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-16" />
        ) : !goals.length ? (
          <p className="text-sm text-muted-foreground">{t('planning.noGoals')}</p>
        ) : (
          <ul className="grid gap-2.5">
            {goals.slice(0, 5).map((g) => {
              const state = goalState(g, today, fmt.settings.working_days)
              return (
                <li key={g.id} className="grid gap-1">
                  <div className="flex items-center gap-2 text-sm">
                    <span className={cn('min-w-0 flex-1 truncate [unicode-bidi:plaintext]', g.owner === me.id && 'font-medium')}>{g.title}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      <span className="font-latin">{g.current}/{g.target}</span>{g.unit && <> <bdi>{g.unit}</bdi></>}
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                    <div className={cn('h-full rounded-full', GOAL_BAR[state])} style={{ width: `${Math.min(100, (g.current / g.target) * 100)}%` }} />
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
