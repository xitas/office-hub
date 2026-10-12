import { AlarmClock, BellRing, CheckSquare } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { EmptyState } from '@/components/common'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useFormat } from '@/lib/format'
import { KIND_ICONS } from '@/lib/timeline'
import type { FollowUpDue } from '@/lib/types'
import { cn } from '@/lib/utils'

/** My client follow-ups due within a week (overdue first): from calls, emails, messages and notes. */
export function FollowUpsWidget({ items, loading, className }: { items: FollowUpDue[] | null | undefined; loading: boolean; className?: string }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  if (!loading && items === null) return null
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center gap-2">
        <BellRing className="size-4 text-muted-foreground" />
        <CardTitle className="flex-1 text-sm font-medium">{t('dashboard.followUps')}</CardTitle>
        <Link to="/log?follow_up=open" className="text-xs text-primary hover:underline">
          {t('dashboard.allFollowUps')}
        </Link>
      </CardHeader>
      <CardContent>
        {loading || !items ? (
          <div className="space-y-2">
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
          </div>
        ) : !items.length ? (
          <EmptyState icon={BellRing} title={t('dashboard.noFollowUps')} className="py-4" />
        ) : (
          <ul className="divide-y">
            {items.map((item) => {
              const Icon = KIND_ICONS[item.kind] ?? BellRing
              return (
                <li key={item.id}>
                  <Link to={item.url} className="flex items-center gap-2.5 py-2 text-sm hover:text-primary">
                    <Icon className="size-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1">
                      <bdi className="block truncate font-medium">{item.title}</bdi>
                      {item.summary && (
                        <span className="block truncate text-xs text-muted-foreground [unicode-bidi:plaintext] ltr:text-left rtl:text-right">
                          {item.summary}
                        </span>
                      )}
                    </span>
                    {item.task_id && <CheckSquare className="size-3.5 shrink-0 text-muted-foreground" aria-label={t('dashboard.hasTask')} />}
                    <span className={cn('inline-flex shrink-0 items-center gap-1 text-xs', item.is_overdue ? 'font-medium text-destructive' : 'text-muted-foreground')}>
                      {item.is_overdue && <AlarmClock className="size-3.5" />}
                      <bdi className="font-latin">{fmt.date(`${item.due_date}T12:00:00`)}</bdi>
                    </span>
                  </Link>
                </li>
              )
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
