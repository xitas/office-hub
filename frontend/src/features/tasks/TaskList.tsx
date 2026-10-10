import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, CheckCircle2, Circle, ClipboardCheck, UserRound } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, Pagination } from '@/components/common'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, apiError } from '@/lib/api'
import type { Task } from '@/lib/tasks'
import type { Paginated } from '@/lib/types'
import { cn } from '@/lib/utils'
import { AssigneeAvatars, DueLabel, PriorityBadge, TaskStatusBadge } from './TaskBits'

/** List view: table on desktop, cards on phones, with one-click complete. */
export function TaskList({
  params,
  page,
  onPage,
  empty,
}: {
  params: Record<string, string | undefined>
  page: number
  onPage: (page: number) => void
  empty: { title: string; hint?: string }
}) {
  const query = useQuery({
    queryKey: ['tasks', 'list', params, page],
    queryFn: async () => (await api.get<Paginated<Task>>('/tasks/', { params: { ...params, page } })).data,
    placeholderData: keepPreviousData,
  })

  if (query.isError) return <ErrorState onRetry={() => void query.refetch()} />
  if (query.isLoading || !query.data)
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-14 rounded-lg" />
        ))}
      </div>
    )
  if (!query.data.results.length)
    return (
      <Card>
        <EmptyState icon={ClipboardCheck} title={empty.title} hint={empty.hint} />
      </Card>
    )
  return (
    <>
      <TaskTable tasks={query.data.results} />
      <TaskCards tasks={query.data.results} />
      <Pagination page={page} count={query.data.count} onPage={onPage} />
    </>
  )
}

/** One-click complete (or reopen). */
function useToggleDone() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (task: Task) =>
      (await api.patch<Task>(`/tasks/${task.id}/`, { status: task.status === 'done' ? 'todo' : 'done' })).data,
    onSuccess: (task) => {
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
      toast.success(task.status === 'done' ? t('tasks.completed', { title: task.title }) : t('tasks.reopened', { title: task.title }))
    },
    onError: (err) => toast.error(apiError(err).message),
  })
}

function DoneButton({ task }: { task: Task }) {
  const { t } = useTranslation()
  const toggle = useToggleDone()
  const done = task.status === 'done'
  return (
    <button
      type="button"
      onClick={() => toggle.mutate(task)}
      disabled={toggle.isPending}
      aria-pressed={done}
      aria-label={t(done ? 'tasks.reopen' : 'tasks.markDone', { title: task.title })}
      title={t(done ? 'tasks.reopen' : 'tasks.markDone', { title: task.title })}
      className={cn(
        'flex size-8 shrink-0 items-center justify-center rounded-full transition-colors disabled:opacity-50',
        done ? 'text-success hover:text-muted-foreground' : 'text-muted-foreground hover:bg-success/10 hover:text-success',
      )}
    >
      {done ? <CheckCircle2 className="size-5" /> : <Circle className="size-5" />}
    </button>
  )
}

/** The linked contact or company, if any. */
export function Related({ task }: { task: Task }) {
  if (!task.contact && !task.company) return null
  const Icon = task.contact ? UserRound : Building2
  return (
    <span className="inline-flex min-w-0 max-w-full items-center gap-1 text-xs text-muted-foreground">
      <Icon className="size-3 shrink-0" />
      <bdi className="truncate">{task.contact ? task.contact_name : task.company_name}</bdi>
    </span>
  )
}

function TaskTable({ tasks }: { tasks: Task[] }) {
  const { t } = useTranslation()
  return (
    <Card className="hidden py-0 md:block">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-12" />
            <TableHead>{t('tasks.fields.title')}</TableHead>
            <TableHead>{t('tasks.fields.assignees')}</TableHead>
            <TableHead>{t('tasks.fields.dueDate')}</TableHead>
            <TableHead>{t('tasks.fields.priority')}</TableHead>
            <TableHead>{t('tasks.fields.status')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tasks.map((task) => (
            <TableRow key={task.id} className={cn(task.is_overdue && 'bg-destructive/5 hover:bg-destructive/10')}>
              <TableCell className="ps-2">
                <DoneButton task={task} />
              </TableCell>
              <TableCell className="max-w-96">
                <Link
                  to={`/tasks/${task.id}`}
                  className={cn('block truncate font-medium hover:text-primary hover:underline', task.status === 'done' && 'text-muted-foreground line-through')}
                >
                  {task.title}
                </Link>
                <Related task={task} />
              </TableCell>
              <TableCell>
                <AssigneeAvatars people={task.assignee_details} />
              </TableCell>
              <TableCell className="whitespace-nowrap text-sm">
                <DueLabel task={task} />
              </TableCell>
              <TableCell>
                <PriorityBadge priority={task.priority} />
              </TableCell>
              <TableCell>
                <TaskStatusBadge status={task.status} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  )
}

function TaskCards({ tasks }: { tasks: Task[] }) {
  return (
    <ul className="grid gap-2 md:hidden">
      {tasks.map((task) => (
        <li key={task.id}>
          <Card className={cn('flex-row items-start gap-2 px-3 py-3', task.is_overdue && 'ring-destructive/40')}>
            <DoneButton task={task} />
            <div className="min-w-0 flex-1">
              <Link
                to={`/tasks/${task.id}`}
                className={cn('block font-medium hover:text-primary', task.status === 'done' && 'text-muted-foreground line-through')}
              >
                {task.title}
              </Link>
              <Related task={task} />
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
                <DueLabel task={task} />
                <PriorityBadge priority={task.priority} />
                <TaskStatusBadge status={task.status} />
              </div>
            </div>
            <AssigneeAvatars people={task.assignee_details} max={2} />
          </Card>
        </li>
      ))}
    </ul>
  )
}
