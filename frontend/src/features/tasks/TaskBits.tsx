import { AlarmClock, CalendarClock } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { UserAvatar } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { useFormat } from '@/lib/format'
import { PRIORITY_STYLES, shortTime, STATUS_STYLES, type Task, type TaskAssignee, type TaskPriority, type TaskStatus } from '@/lib/tasks'
import { cn } from '@/lib/utils'

export function TaskStatusBadge({ status, className }: { status: TaskStatus; className?: string }) {
  const { t } = useTranslation()
  return (
    <Badge variant="outline" className={cn(STATUS_STYLES[status], className)}>
      {t(`tasks.statuses.${status}`)}
    </Badge>
  )
}

export function PriorityBadge({ priority, className }: { priority: TaskPriority; className?: string }) {
  const { t } = useTranslation()
  return (
    <Badge variant="outline" className={cn(PRIORITY_STYLES[priority], className)}>
      {t(`tasks.priorities.${priority}`)}
    </Badge>
  )
}

/** Due date (and time); overdue tasks are marked in red with an icon and the word "Overdue". */
export function DueLabel({ task, className }: { task: Pick<Task, 'due_date' | 'due_time' | 'is_overdue' | 'status'>; className?: string }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  if (!task.due_date) return <span className={cn('text-muted-foreground', className)}>{t('tasks.noDueDate')}</span>
  const time = shortTime(task.due_time)
  const text = (
    <span className="font-latin" dir="ltr">
      {/* noon: the same calendar day in any browser time zone */}
      {fmt.date(`${task.due_date}T12:00:00`)}
      {time && ` ${time}`}
    </span>
  )
  if (task.is_overdue) {
    return (
      <span className={cn('inline-flex items-center gap-1 font-medium text-destructive', className)}>
        <AlarmClock className="size-3.5 shrink-0" />
        {text}
        <span>· {t('tasks.overdue')}</span>
      </span>
    )
  }
  return (
    <span className={cn('inline-flex items-center gap-1', task.status === 'done' && 'text-muted-foreground', className)}>
      <CalendarClock className="size-3.5 shrink-0 text-muted-foreground" />
      {text}
    </span>
  )
}

export function AssigneeAvatars({ people, max = 3 }: { people: TaskAssignee[]; max?: number }) {
  const shown = people.slice(0, max)
  const more = people.length - shown.length
  return (
    <span className="flex items-center -space-x-1.5 rtl:space-x-reverse" title={people.map((p) => p.full_name).join(', ')}>
      {shown.map((p) => (
        <UserAvatar key={p.id} name={p.full_name} src={p.avatar} className="size-7 ring-2 ring-card" />
      ))}
      {more > 0 && (
        <span className="z-10 flex size-7 items-center justify-center rounded-full bg-muted text-[11px] font-medium ring-2 ring-card font-latin">
          +{more}
        </span>
      )}
    </span>
  )
}
