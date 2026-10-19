import { BellRing, CheckCircle2, CheckSquare, Clock3, TriangleAlert } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { useFormat } from '@/lib/format'
import { officeDate } from '@/lib/tasks'
import { staleDays, type CallDetails, type EmailDetails, type TimelineItem } from '@/lib/timeline'
import { cn } from '@/lib/utils'

/** The one-line title of a logged call, email, WhatsApp message, meeting or note. */
export function EntryTitle({ item }: { item: TimelineItem }) {
  const { t } = useTranslation()
  if (item.kind === 'call') {
    const d = item.details as CallDetails
    return (
      <span className="font-medium">
        {t(`timeline.callTitle.${d.direction ?? 'out'}`)}
        {d.outcome && <span className="font-normal text-muted-foreground"> · {t(`timeline.outcomes.${d.outcome}`)}</span>}
        {d.duration_minutes != null && (
          <span className="font-normal text-muted-foreground"> · {t('timeline.minutes', { count: d.duration_minutes })}</span>
        )}
      </span>
    )
  }
  if (item.kind === 'email' || item.kind === 'whatsapp') {
    const d = item.details as EmailDetails
    return (
      <span className="font-medium">
        {t(`timeline.${item.kind}Title.${d.direction ?? 'out'}`)}
        {d.subject && (
          <span className="font-normal text-muted-foreground">
            {' · '}
            <bdi>{d.subject}</bdi>
          </span>
        )}
      </span>
    )
  }
  if (item.kind === 'visit') {
    const d = item.details as { visit_id?: number; title?: string; visit_visible?: boolean }
    return (
      <span className="font-medium">
        {t('timeline.kinds.visit')}
        {d.visit_id && (
          <>
            {' · '}
            {d.visit_visible === false ? (
              <bdi className="font-normal">{d.title ?? item.summary}</bdi>
            ) : (
              <Link to={`/visits?visit=${d.visit_id}`} className="font-normal text-primary hover:underline"><bdi>{d.title ?? item.summary}</bdi></Link>
            )}
          </>
        )}
      </span>
    )
  }
  const known = ['note', 'meeting'].includes(item.kind)
  return <span className="font-medium">{known ? t(`timeline.kinds.${item.kind}`) : item.kind}</span>
}

/** Follow-up date and where it stands: its task (and who it's for), done, or no task. */
export function FollowUpStatus({ item, className }: { item: TimelineItem; className?: string }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  if (!item.follow_up_on) return null
  const task = item.follow_up_task
  const done = !!item.follow_up_done
  const late = !done && item.follow_up_on < officeDate(fmt.settings.timezone)
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-x-2 gap-y-1', className)}>
      <Badge
        variant="outline"
        className={cn(
          'gap-1 font-normal',
          done && 'border-success/40 text-success',
          late && 'border-destructive/40 text-destructive',
        )}
      >
        {done ? <CheckCircle2 className="size-3" /> : <BellRing className="size-3" />}
        {done ? t('timeline.followUpDone', { date: fmt.date(item.follow_up_on) }) : t('timeline.followUpOn', { date: fmt.date(item.follow_up_on) })}
      </Badge>
      {task ? (
        <Link to={`/tasks/${task.id}`} className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
          <CheckSquare className="size-3.5" />
          {task.assignees.length ? t('timeline.followUpTaskFor', { names: task.assignees.join(', ') }) : t('timeline.followUpTaskLink')}
        </Link>
      ) : (
        item.follow_up_skipped && <span className="text-xs text-muted-foreground">{t('timeline.followUpNoTask')}</span>
      )}
    </span>
  )
}

/** "Last contacted 3 days ago" (latest call, meeting, email or WhatsApp), and for an open lead with no
 *  contact for a while, "No contact in N days". `lead` is given for contacts (companies have no status). */
export function LastContacted({
  at,
  lead,
  compact,
  className,
}: {
  at: string | null | undefined
  lead?: { status: string; created_at?: string }
  compact?: boolean
  className?: string
}) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const stale = lead ? staleDays({ ...lead, last_contacted_at: at }) : null
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground', className)}>
      {!compact && (
        <span className="inline-flex items-center gap-1" title={at ? fmt.dateTime(at) : undefined}>
          <Clock3 className="size-3.5" />
          {at ? t('log.lastContacted', { when: fmt.relative(at) }) : t('log.neverContacted')}
        </span>
      )}
      {compact && at && !stale && (
        <span className="inline-flex items-center gap-1" title={t('log.lastContactedTitle', { date: fmt.dateTime(at) })}>
          <Clock3 className="size-3" />
          {fmt.relative(at)}
        </span>
      )}
      {stale !== null && (
        <span className="inline-flex items-center gap-1 font-medium text-amber-700 dark:text-amber-400" title={t('log.staleHint')}>
          <TriangleAlert className="size-3.5" />
          {t('log.noContactIn', { count: stale })}
        </span>
      )}
    </span>
  )
}
