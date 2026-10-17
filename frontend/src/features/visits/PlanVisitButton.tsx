import { MapPin } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { cn } from '@/lib/utils'
import { useVisits, VISIT_TONE } from '@/lib/visits'
import { VisitDialog, type VisitPrefill } from './VisitDialog'

/** "Plan visit" on a contact, company, vendor or task page, with what the page already knows filled in. */
export function PlanVisitButton({ prefill, size = 'sm' }: { prefill: VisitPrefill; size?: 'sm' | 'default' }) {
  const { t } = useTranslation()
  const canPlan = usePermission('visits.create')
  const [open, setOpen] = useState(false)
  if (!canPlan) return null
  return (
    <>
      <Button variant="outline" size={size} onClick={() => setOpen(true)}>
        <MapPin className="size-3.5" />
        {t('visits.plan')}
      </Button>
      {open && <VisitDialog prefill={prefill} onClose={() => setOpen(false)} />}
    </>
  )
}

/** On a task: the visits that carry it out, and "Plan visit" for it. */
export function TaskVisits({ task }: { task: { id: number; title: string; contact: number | null; contact_name: string | null; company: number | null; company_name: string | null } }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const canSee = usePermission('visits.view')
  const { data } = useVisits({ task: task.id }, canSee)
  if (!canSee) return null
  const target = task.contact
    ? { target: { contact: task.contact }, name: task.contact_name ?? '', hint: '', type: 'contact' as const }
    : task.company
      ? { target: { company: task.company }, name: task.company_name ?? '', hint: '', type: 'company' as const }
      : undefined
  return (
    <Card className="gap-3">
      <CardHeader className="flex flex-row items-center gap-2">
        <MapPin className="size-4 text-muted-foreground" />
        <CardTitle className="flex-1 text-sm font-medium">{t('visits.title')}</CardTitle>
        <PlanVisitButton prefill={{ target, title: task.title, task: { id: task.id, title: task.title } }} />
      </CardHeader>
      <CardContent>
        {!data?.length ? (
          <p className="text-sm text-muted-foreground">{t('visits.noneForTask')}</p>
        ) : (
          <ul className="grid gap-2 text-sm">
            {data.map((v) => (
              <li key={v.id} className="flex flex-wrap items-center gap-2">
                <Link to={`/visits?visit=${v.id}`} className="min-w-0 flex-1 truncate text-primary hover:underline [unicode-bidi:plaintext]">{v.title}</Link>
                <span className="text-xs text-muted-foreground">{fmt.date(v.start)} {fmt.time(v.start)}</span>
                <Badge variant="outline" className={cn('font-normal', VISIT_TONE[v.status])}>{t(`visits.status.${v.status}`)}</Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

