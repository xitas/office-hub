import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckSquare, Plus, UserRound } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, FormDialog } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { usePermission } from '@/lib/permissions'
import type { Task } from '@/lib/tasks'
import type { Paginated } from '@/lib/types'
import { cn } from '@/lib/utils'
import { AssigneeAvatars, DueLabel, PriorityBadge, RepeatMark } from './TaskBits'
import { TaskForm, type Linked } from './TaskForm'
import { DoneButton } from './TaskList'

type Target = { contact: number; name: string } | { company: number; name: string }

/** Open tasks linked to a contact or company, plus those completed in the last two weeks.
 *  A company also lists its contacts' tasks, each marked with the contact's name. */
export function LinkedTasks({ target }: { target: Target }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const canView = usePermission('tasks.view')
  const canCreate = usePermission('tasks.create')
  const [adding, setAdding] = useState(false)
  const isCompany = 'company' in target
  const params = isCompany ? { related_company: target.company } : { contact: target.contact }

  const { data, isLoading } = useQuery({
    queryKey: ['tasks', 'linked', params],
    queryFn: async () =>
      (await api.get<Paginated<Task>>('/tasks/', { params: { ...params, recent: true, page_size: 50 } })).data.results,
    enabled: canView,
  })
  if (!canView) return null

  const open = data?.filter((task) => task.status !== 'done') ?? []
  const done = data?.filter((task) => task.status === 'done') ?? []
  const linked: Linked = isCompany
    ? { type: 'company', id: target.company, name: target.name }
    : { type: 'contact', id: target.contact, name: target.name }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center gap-2">
        <CheckSquare className="size-4 text-muted-foreground" />
        <CardTitle className="flex-1">
          {t('tasks.title')}
          {open.length > 0 && <span className="ms-1.5 text-sm font-normal text-muted-foreground font-latin">({open.length})</span>}
        </CardTitle>
        {canCreate && (
          <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
            <Plus className="size-4" />
            {t('tasks.add')}
          </Button>
        )}
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-3 px-0">
        {isLoading ? (
          <div className="space-y-2 px-4">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : !data?.length ? (
          <EmptyState icon={CheckSquare} title={t('tasks.linked.empty')} className="py-4" />
        ) : (
          <>
            {open.length > 0 && <TaskRows tasks={open} showContact={isCompany} />}
            {done.length > 0 && (
              <div>
                <p className="px-4 pb-1 text-xs font-medium text-muted-foreground">{t('tasks.linked.recentlyDone')}</p>
                <TaskRows tasks={done} showContact={isCompany} />
              </div>
            )}
          </>
        )}
      </CardContent>
      {adding && (
        <FormDialog open onOpenChange={setAdding} title={t('tasks.add')}>
          <TaskForm
            defaults={{ linked }}
            onCancel={() => setAdding(false)}
            onSaved={() => {
              setAdding(false)
              toast.success(t('tasks.created'))
              void queryClient.invalidateQueries({ queryKey: ['tasks'] })
              void queryClient.invalidateQueries({ queryKey: ['timeline'] })
            }}
          />
        </FormDialog>
      )}
    </Card>
  )
}

function TaskRows({ tasks, showContact }: { tasks: Task[]; showContact: boolean }) {
  return (
    <ul className="divide-y">
      {tasks.map((task) => (
        <li key={task.id} className={cn('flex items-start gap-2 px-2 py-2', task.is_overdue && 'bg-destructive/5')}>
          <DoneButton task={task} />
          <div className="min-w-0 flex-1 pt-1">
            <Link
              to={`/tasks/${task.id}`}
              className={cn('block truncate text-sm font-medium hover:text-primary hover:underline', task.status === 'done' && 'text-muted-foreground line-through')}
            >
              {task.title}
            </Link>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              {task.due_date && <DueLabel task={task} />}
              {task.status !== 'done' && <PriorityBadge priority={task.priority} />}
              <RepeatMark task={task} />
              {showContact && task.contact && (
                <span className="inline-flex min-w-0 items-center gap-1 text-muted-foreground">
                  <UserRound className="size-3 shrink-0" />
                  <bdi className="truncate">{task.contact_name}</bdi>
                </span>
              )}
            </div>
          </div>
          <AssigneeAvatars people={task.assignee_details} max={2} />
        </li>
      ))}
    </ul>
  )
}
