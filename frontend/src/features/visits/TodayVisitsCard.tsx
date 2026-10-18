import { MapPin } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { cn } from '@/lib/utils'
import { useVisits, VISIT_TONE } from '@/lib/visits'

/** Today's field visits: mine, or my team's for managers and admins. Loaded on its own, not part of /dashboard/. */
export function TodayVisitsCard({ className }: { className?: string }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const team = usePermission('visits.delete')
  const { data, isLoading } = useVisits({ scope: 'today' })
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center gap-2">
        <MapPin className="size-4 text-muted-foreground" />
        <CardTitle className="flex-1 text-sm font-medium">{t(team ? 'visits.todayTeam' : 'visits.today')}</CardTitle>
        {!!data?.length && <Badge variant="secondary" className="font-latin">{data.length}</Badge>}
        <Link to="/visits" className="text-xs text-primary hover:underline">{t('visits.open')}</Link>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-16" />
        ) : !data?.length ? (
          <p className="text-sm text-muted-foreground">{t('visits.noneToday')}</p>
        ) : (
          <ul className="grid gap-2">
            {data.slice(0, 6).map((v) => (
              <li key={v.id}>
                <Link to={`/visits?visit=${v.id}`} className="grid gap-0.5 rounded-md px-1 py-0.5 text-sm hover:bg-muted">
                  <span className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate font-medium [unicode-bidi:plaintext]">{v.title}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">{fmt.time(v.start)}–{fmt.time(v.end)}</span>
                  </span>
                  <span className="flex items-center gap-2 text-xs text-muted-foreground">
                    <bdi className="min-w-0 flex-1 truncate">{team ? `${v.assigned_to_name} · ${v.place}` : v.place}</bdi>
                    {v.status === 'planned' && v.checks.some((c) => c.user === v.assigned_to) && (
                      <Badge variant="outline" className="border-emerald-500/50 font-normal text-emerald-700 dark:text-emerald-300">
                        {v.checks.find((c) => c.user === v.assigned_to)?.checked_out_at ? t('visits.checks.left') : t('visits.checks.arrived')}
                      </Badge>
                    )}
                    {v.status !== 'planned' && <Badge variant="outline" className={cn('font-normal', VISIT_TONE[v.status])}>{t(`visits.status.${v.status}`)}</Badge>}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
