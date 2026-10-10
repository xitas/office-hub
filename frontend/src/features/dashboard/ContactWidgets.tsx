import { ArrowRight, History, PieChart } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { EmptyState } from '@/components/common'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useFormat } from '@/lib/format'
import { KIND_ICONS, KIND_STYLES, type CallDetails, type StatusDetails, type TimelineItem } from '@/lib/timeline'
import type { ContactStatus, DashboardData } from '@/lib/types'
import { cn } from '@/lib/utils'

// Theme tokens only, so the bars work in light and dark mode.
const BAR_STYLES: Record<ContactStatus, string> = {
  new: 'bg-muted-foreground/40',
  contacted: 'bg-primary',
  in_discussion: 'bg-warning',
  won: 'bg-success',
  lost: 'bg-destructive/70',
}

function Widget({
  title,
  icon: Icon,
  action,
  children,
  className,
}: {
  title: string
  icon: typeof History
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
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

/** Lead counts per status: own contacts for staff, the department for managers, everyone for admins. */
export function ContactsByStatusWidget({
  data,
  loading,
  className,
}: {
  data: DashboardData['contacts_by_status'] | undefined
  loading: boolean
  className?: string
}) {
  const { t } = useTranslation()
  const fmt = useFormat()
  if (!loading && !data) return null
  const max = Math.max(1, ...(data?.counts.map((c) => c.count) ?? [1]))
  const title = t(`dashboard.contactsByStatus.${data?.scope ?? 'mine'}`)
  return (
    <Widget
      title={title}
      icon={PieChart}
      className={className}
      action={
        data && (
          <Link to="/pipeline" className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
            {t('dashboard.openPipeline')}
            <ArrowRight className="size-3 rtl:rotate-180" />
          </Link>
        )
      }
    >
      {loading || !data ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-5 w-full" />
          ))}
        </div>
      ) : data.total === 0 ? (
        <EmptyState icon={PieChart} title={t('dashboard.noContacts')} className="py-4" />
      ) : (
        <ul className="grid gap-2.5" aria-label={title}>
          {data.counts.map((c) => (
            <li key={c.status} className="grid grid-cols-[7.5rem_minmax(0,1fr)_2.5rem] items-center gap-3">
              <StatusBadge status={c.status} className="justify-self-start" />
              <span className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
                <span className={cn('block h-full rounded-full', BAR_STYLES[c.status])} style={{ width: `${(c.count / max) * 100}%` }} />
              </span>
              <span className="text-end text-sm font-medium font-latin">{fmt.number(c.count)}</span>
            </li>
          ))}
          <li className="mt-1 flex justify-between border-t pt-2 text-xs text-muted-foreground">
            <span>{t('dashboard.total')}</span>
            <span className="font-latin">{fmt.number(data.total)}</span>
          </li>
        </ul>
      )}
    </Widget>
  )
}

/** Latest notes, calls, meetings and status changes on contacts and companies the user can see. */
export function ClientActivityWidget({
  items,
  loading,
  className,
}: {
  items: TimelineItem[] | null | undefined
  loading: boolean
  className?: string
}) {
  const { t } = useTranslation()
  const fmt = useFormat()
  if (!loading && items === null) return null
  const headline = (item: TimelineItem) => {
    if (item.kind === 'call') return t(`timeline.callTitle.${(item.details as CallDetails).direction ?? 'out'}`)
    if (item.kind === 'status') return t('timeline.statusChanged')
    if (item.kind === 'note' || item.kind === 'meeting') return t(`timeline.kinds.${item.kind}`)
    return item.kind
  }
  return (
    <Widget title={t('dashboard.clientActivity')} icon={History} className={className}>
      {loading || !items ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : !items.length ? (
        <EmptyState icon={History} title={t('dashboard.noClientActivity')} hint={t('dashboard.noClientActivityHint')} className="py-4" />
      ) : (
        <ul className="grid gap-3">
          {items.map((item) => {
            const Icon = KIND_ICONS[item.kind] ?? History
            const record = item.contact
              ? { name: item.contact.name, to: `/contacts/${item.contact.id}` }
              : item.company
                ? { name: item.company.name, to: `/companies/${item.company.id}` }
                : null
            return (
              <li key={item.id} className="flex gap-3">
                <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-full', KIND_STYLES[item.kind] ?? KIND_STYLES.status)}>
                  <Icon className="size-4" />
                </span>
                <div className="min-w-0 flex-1 text-sm">
                  <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                    <span className="font-medium">{headline(item)}</span>
                    {item.kind === 'status' && <StatusBadge status={(item.details as unknown as StatusDetails).to} />}
                    {record && (
                      <>
                        <span className="text-muted-foreground">·</span>
                        <Link to={record.to} className="text-primary hover:underline">
                          <bdi>{record.name}</bdi>
                        </Link>
                      </>
                    )}
                  </p>
                  {item.summary && (
                    <p dir="auto" className="line-clamp-2 text-muted-foreground">
                      {item.summary}
                    </p>
                  )}
                  <p className="text-xs text-muted-foreground">
                    <time dateTime={item.occurred_at} title={fmt.dateTime(item.occurred_at)}>
                      {fmt.relative(item.occurred_at)}
                    </time>
                    {item.created_by_name && (
                      <>
                        {' · '}
                        <bdi>{item.created_by_name}</bdi>
                      </>
                    )}
                  </p>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </Widget>
  )
}
