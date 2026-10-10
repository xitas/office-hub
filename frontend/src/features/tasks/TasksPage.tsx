import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, CheckCircle2, Circle, ClipboardCheck, Plus, Search, UserRound } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, FormDialog, PageHeader, Pagination, SimpleSelect } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, apiError } from '@/lib/api'
import { ALL } from '@/lib/contacts'
import { usePermission } from '@/lib/permissions'
import {
  QUICK_FILTERS,
  TASK_PRIORITIES,
  TASK_SORTS,
  TASK_STATUSES,
  useTaskAssignees,
  type QuickFilter,
  type Task,
} from '@/lib/tasks'
import type { Paginated } from '@/lib/types'
import { cn, useDebouncedValue } from '@/lib/utils'
import { AssigneeAvatars, DueLabel, PriorityBadge, TaskStatusBadge } from './TaskBits'
import { TaskForm } from './TaskForm'

const VIEWS = Object.keys(QUICK_FILTERS) as QuickFilter[]

export function TasksPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const canCreate = usePermission('tasks.create')
  const people = useTaskAssignees()

  const view: QuickFilter = VIEWS.includes(params.get('view') as QuickFilter) ? (params.get('view') as QuickFilter) : 'mine'
  const creating = params.get('new') === '1'
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState(ALL)
  const [priority, setPriority] = useState(ALL)
  const [assignee, setAssignee] = useState(ALL)
  const [sort, setSort] = useState('default')
  const [page, setPage] = useState(1)
  const q = useDebouncedValue(search.trim())

  const reset = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v)
    setPage(1)
  }
  const setView = (v: QuickFilter) => {
    setPage(1)
    setParams(v === 'mine' ? {} : { view: v }, { replace: true })
  }

  const query = useQuery({
    queryKey: ['tasks', 'list', { view, q, status, priority, assignee, sort, page }],
    queryFn: async () =>
      (
        await api.get<Paginated<Task>>('/tasks/', {
          params: {
            ...QUICK_FILTERS[view],
            search: q || undefined,
            status: status === ALL ? undefined : status,
            priority: priority === ALL ? undefined : priority,
            assigned_to: assignee === ALL ? undefined : assignee,
            ordering: sort === 'default' ? undefined : sort,
            page,
          },
        })
      ).data,
    placeholderData: keepPreviousData,
  })

  const closeCreate = () => setParams(view === 'mine' ? {} : { view }, { replace: true })
  const filtered = q !== '' || status !== ALL || priority !== ALL || assignee !== ALL

  return (
    <>
      <PageHeader
        title={t('tasks.title')}
        subtitle={t('tasks.subtitle')}
        actions={
          canCreate && (
            <Button onClick={() => setParams({ ...(view !== 'mine' && { view }), new: '1' })}>
              <Plus className="size-4" />
              {t('tasks.add')}
            </Button>
          )
        }
      />

      <div role="tablist" aria-label={t('tasks.views.label')} className="mb-3 flex gap-1 overflow-x-auto rounded-lg bg-muted p-1 sm:inline-flex">
        {VIEWS.map((v) => (
          <button
            key={v}
            role="tab"
            type="button"
            aria-selected={view === v}
            onClick={() => setView(v)}
            className={cn(
              'shrink-0 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
              view === v ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {t(`tasks.views.${v}`)}
          </button>
        ))}
      </div>

      <div className="mb-4 grid grid-cols-2 gap-2 lg:grid-cols-[minmax(0,1fr)_10rem_10rem_12rem_11rem]">
        <div className="relative col-span-2 lg:col-span-1">
          <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => reset(setSearch)(e.target.value)} placeholder={t('tasks.searchPlaceholder')} className="ps-8" aria-label={t('tasks.searchPlaceholder')} />
        </div>
        <SimpleSelect
          value={status}
          onChange={reset(setStatus)}
          options={[{ value: ALL, label: t('tasks.allStatuses') }, ...TASK_STATUSES.map((s) => ({ value: s, label: t(`tasks.statuses.${s}`) }))]}
        />
        <SimpleSelect
          value={priority}
          onChange={reset(setPriority)}
          options={[{ value: ALL, label: t('tasks.allPriorities') }, ...TASK_PRIORITIES.map((p) => ({ value: p, label: t(`tasks.priorities.${p}`) }))]}
        />
        <SimpleSelect
          value={assignee}
          onChange={reset(setAssignee)}
          options={[{ value: ALL, label: t('tasks.everyone') }, ...people.map((u) => ({ value: String(u.id), label: u.full_name }))]}
        />
        <SimpleSelect
          value={sort}
          onChange={reset(setSort)}
          options={TASK_SORTS.map((s) => ({ value: s, label: t(`tasks.sorts.${s}`) }))}
        />
      </div>

      {query.isError ? (
        <ErrorState onRetry={() => void query.refetch()} />
      ) : query.isLoading || !query.data ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-14 rounded-lg" />
          ))}
        </div>
      ) : !query.data.results.length ? (
        <Card>
          <EmptyState
            icon={ClipboardCheck}
            title={t(filtered ? 'tasks.emptyFiltered' : `tasks.empty.${view}`)}
            hint={!filtered && canCreate && view !== 'overdue' ? t('tasks.emptyHint') : undefined}
          />
        </Card>
      ) : (
        <>
          <TaskTable tasks={query.data.results} />
          <TaskCards tasks={query.data.results} />
          <Pagination page={page} count={query.data.count} onPage={setPage} />
        </>
      )}

      {creating && canCreate && (
        <FormDialog open onOpenChange={(o) => !o && closeCreate()} title={t('tasks.add')}>
          <TaskForm
            onCancel={closeCreate}
            onSaved={(task) => {
              void queryClient.invalidateQueries({ queryKey: ['tasks'] })
              toast.success(t('tasks.created'))
              navigate(`/tasks/${task.id}`, { replace: true })
            }}
          />
        </FormDialog>
      )}
    </>
  )
}

/** One-click complete (or reopen) from the list. */
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

function Related({ task }: { task: Task }) {
  if (task.contact)
    return (
      <span className="inline-flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
        <UserRound className="size-3 shrink-0" />
        <bdi className="truncate">{task.contact_name}</bdi>
      </span>
    )
  if (task.company)
    return (
      <span className="inline-flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
        <Building2 className="size-3 shrink-0" />
        <bdi className="truncate">{task.company_name}</bdi>
      </span>
    )
  return null
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
