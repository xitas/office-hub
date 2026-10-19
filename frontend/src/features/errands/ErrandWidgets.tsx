import { CheckSquare, Hand, Send } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ERRAND_ICONS, ERRAND_TONE, useErrands } from '@/lib/errands'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { cn } from '@/lib/utils'
import { ErrandDialog, type ErrandPrefill } from './ErrandDialog'

/** "New errand" with what the page already knows (a vendor, a task). */
export function ErrandButton({ prefill, size = 'sm' }: { prefill: ErrandPrefill; size?: 'sm' | 'default' }) {
  const { t } = useTranslation()
  const can = usePermission('errands.create')
  const [open, setOpen] = useState(false)
  if (!can) return null
  return (
    <>
      <Button variant="outline" size={size} onClick={() => setOpen(true)}>
        <Send className="size-3.5 rtl:-scale-x-100" />
        {t('errands.new')}
      </Button>
      {open && <ErrandDialog prefill={prefill} onClose={() => setOpen(false)} />}
    </>
  )
}

/** Today's errands on the dashboard: mine and ones waiting for someone (managers and admins: the team's). Loaded on its own. */
export function TodayErrandsCard({ className }: { className?: string }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const { data, isLoading } = useErrands({ scope: 'today' })
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center gap-2">
        <Hand className="size-4 text-muted-foreground" />
        <CardTitle className="flex-1 text-sm font-medium">{t('errands.today')}</CardTitle>
        {!!data?.length && <Badge variant="secondary" className="font-latin">{data.length}</Badge>}
        <Link to="/errands" className="text-xs text-primary hover:underline">{t('visits.open')}</Link>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-16" />
        ) : !data?.length ? (
          <p className="text-sm text-muted-foreground">{t('errands.noneToday')}</p>
        ) : (
          <ul className="grid gap-2">
            {data.slice(0, 6).map((e) => {
              const Icon = ERRAND_ICONS[e.kind]
              return (
                <li key={e.id}>
                  <Link to={`/errands?errand=${e.id}`} className="grid gap-0.5 rounded-md px-1 py-0.5 text-sm hover:bg-muted">
                    <span className="flex items-center gap-2">
                      <Icon className="size-3.5 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate font-medium [unicode-bidi:plaintext]">{e.title}</span>
                      {e.due_at && <span className="shrink-0 text-xs text-muted-foreground">{fmt.time(e.due_at)}</span>}
                    </span>
                    <span className="flex items-center gap-2 text-xs text-muted-foreground">
                      <bdi className="min-w-0 flex-1 truncate">{e.assigned_to_name ? `${e.assigned_to_name} · ${e.place}` : e.place}</bdi>
                      <Badge variant="outline" className={cn('font-normal', ERRAND_TONE[e.status])}>{t(`errands.status.${e.status}`)}</Badge>
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

/** On a task: the errands that carry it out, and "New errand" for it. */
export function TaskErrands({ task }: { task: { id: number; title: string; contact: number | null; contact_name: string | null; company: number | null; company_name: string | null } }) {
  const { t } = useTranslation()
  const can = usePermission('errands.view')
  const { data } = useErrands({ task: task.id }, can)
  if (!can) return null
  const target = task.contact
    ? { target: { contact: task.contact }, name: task.contact_name ?? '', hint: '', type: 'contact' as const }
    : task.company
      ? { target: { company: task.company }, name: task.company_name ?? '', hint: '', type: 'company' as const }
      : undefined
  return (
    <Card className="gap-3">
      <CardHeader className="flex flex-row items-center gap-2">
        <CheckSquare className="size-4 text-muted-foreground" />
        <CardTitle className="flex-1 text-sm font-medium">{t('errands.title')}</CardTitle>
        <ErrandButton prefill={{ target, title: task.title, task: { id: task.id, title: task.title } }} />
      </CardHeader>
      <CardContent>
        {!data?.length ? (
          <p className="text-sm text-muted-foreground">{t('errands.noneForTask')}</p>
        ) : (
          <ul className="grid gap-2 text-sm">
            {data.map((e) => (
              <li key={e.id} className="flex flex-wrap items-center gap-2">
                <Link to={`/errands?errand=${e.id}`} className="min-w-0 flex-1 truncate text-primary hover:underline [unicode-bidi:plaintext]">{e.title}</Link>
                <Badge variant="outline" className={cn('font-normal', ERRAND_TONE[e.status])}>{t(`errands.status.${e.status}`)}</Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
