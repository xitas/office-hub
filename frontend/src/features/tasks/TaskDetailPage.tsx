import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Building2, CalendarClock, CheckCircle2, ClipboardCheck, Flag, Link2, Pencil, Trash2, UserRound, Users } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, SimpleSelect, UserAvatar } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { api, apiError } from '@/lib/api'
import { useConfirm } from '@/lib/confirm'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { TASK_STATUSES, useTask, type Task, type TaskStatus } from '@/lib/tasks'
import { cn } from '@/lib/utils'
import { DueLabel, PriorityBadge, TaskStatusBadge } from './TaskBits'
import { TaskForm } from './TaskForm'

function Detail({ icon: Icon, label, children }: { icon: typeof Flag; label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground">{label}</p>
        <div className="text-sm break-words">{children}</div>
      </div>
    </div>
  )
}

export function TaskDetailPage() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const confirm = useConfirm()
  const canEdit = usePermission('tasks.edit')
  const [editing, setEditing] = useState(false)
  const key = ['tasks', 'detail', id]
  const { data: task, isLoading, isError, error, refetch } = useTask(id)

  const saved = (updated: Task) => {
    queryClient.setQueryData(key, updated)
    void queryClient.invalidateQueries({ queryKey: ['tasks', 'list'] })
  }

  const setStatus = useMutation({
    mutationFn: async (status: TaskStatus) => (await api.patch<Task>(`/tasks/${id}/`, { status })).data,
    onSuccess: (updated) => {
      saved(updated)
      toast.success(t('tasks.statusChanged', { status: t(`tasks.statuses.${updated.status}`) }))
    },
    onError: (err) => toast.error(apiError(err).message),
  })

  const remove = useMutation({
    mutationFn: () => api.delete(`/tasks/${id}/`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
      toast.success(t('common.deleted'))
      navigate('/tasks')
    },
    onError: (err) => toast.error(apiError(err).message),
  })

  const back = (
    <Button variant="ghost" size="sm" className="-ms-2 mb-3" nativeButton={false} render={<Link to="/tasks" />}>
      <ArrowLeft className="size-4 rtl:rotate-180" />
      {t('tasks.back')}
    </Button>
  )

  if (isLoading) return <Skeleton className="h-96 max-w-3xl rounded-xl" />
  if (isError || !task) {
    const notFound = (error as { response?: { status?: number } } | null)?.response?.status === 404
    return (
      <>
        {back}
        {notFound ? (
          <EmptyState icon={ClipboardCheck} title={t('tasks.notFound')} hint={t('tasks.notFoundHint')} />
        ) : (
          <ErrorState onRetry={() => void refetch()} />
        )}
      </>
    )
  }

  const askDelete = async () => {
    const ok = await confirm({
      title: t('tasks.deleteTitle', { title: task.title }),
      description: t('tasks.deleteHint'),
      confirmLabel: t('common.delete'),
      destructive: true,
    })
    if (ok) remove.mutate()
  }

  return (
    <div className="max-w-3xl">
      {back}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className={cn('text-2xl font-semibold tracking-tight break-words', task.status === 'done' && 'text-muted-foreground line-through')}>
            {task.title}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <TaskStatusBadge status={task.status} />
            <PriorityBadge priority={task.priority} />
            {task.is_overdue && <DueLabel task={task} className="text-sm" />}
          </div>
        </div>
        {!editing && (
          <div className="flex shrink-0 flex-wrap gap-2">
            {canEdit && (
              <SimpleSelect
                className="w-auto min-w-36"
                value={task.status}
                disabled={setStatus.isPending}
                onChange={(v) => setStatus.mutate(v as TaskStatus)}
                options={TASK_STATUSES.map((s) => ({ value: s, label: t(`tasks.statuses.${s}`) }))}
              />
            )}
            {canEdit && (
              <Button variant="outline" onClick={() => setEditing(true)}>
                <Pencil className="size-4" />
                {t('common.edit')}
              </Button>
            )}
            {task.can_delete && (
              <Button variant="destructive" onClick={() => void askDelete()} disabled={remove.isPending}>
                <Trash2 className="size-4" />
                {t('common.delete')}
              </Button>
            )}
          </div>
        )}
      </div>

      {editing ? (
        <Card>
          <CardHeader>
            <CardTitle>{t('tasks.edit')}</CardTitle>
          </CardHeader>
          <CardContent>
            <TaskForm
              task={task}
              onCancel={() => setEditing(false)}
              onSaved={(updated) => {
                saved(updated)
                setEditing(false)
                toast.success(t('common.saved'))
              }}
            />
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          <Card>
            <CardHeader>
              <CardTitle>{t('tasks.details')}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-5 sm:grid-cols-2">
              <Detail icon={CalendarClock} label={t('tasks.fields.dueDate')}>
                <DueLabel task={task} />
              </Detail>
              <Detail icon={Flag} label={t('tasks.fields.priority')}>
                {t(`tasks.priorities.${task.priority}`)}
              </Detail>
              <Detail icon={Users} label={t('tasks.fields.assignees')}>
                <ul className="mt-1 grid gap-1.5">
                  {task.assignee_details.map((p) => (
                    <li key={p.id} className="flex items-center gap-2">
                      <UserAvatar name={p.full_name} src={p.avatar} className="size-6" />
                      <bdi>{p.full_name}</bdi>
                    </li>
                  ))}
                </ul>
              </Detail>
              <Detail icon={Link2} label={t('tasks.fields.relatedTo')}>
                {task.contact ? (
                  <Link to={`/contacts/${task.contact}`} className="inline-flex items-center gap-1 text-primary hover:underline">
                    <UserRound className="size-3.5" />
                    <bdi>{task.contact_name}</bdi>
                  </Link>
                ) : task.company ? (
                  <Link to={`/companies/${task.company}`} className="inline-flex items-center gap-1 text-primary hover:underline">
                    <Building2 className="size-3.5" />
                    <bdi>{task.company_name}</bdi>
                  </Link>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </Detail>
              {task.completed_at && (
                <Detail icon={CheckCircle2} label={t('tasks.completedAt')}>
                  {fmt.dateTime(task.completed_at)}
                </Detail>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t('tasks.fields.description')}</CardTitle>
            </CardHeader>
            <CardContent>
              {task.description ? (
                <p dir="auto" className="text-sm whitespace-pre-wrap break-words">
                  {task.description}
                </p>
              ) : (
                <p className="text-sm text-muted-foreground">{t('tasks.noDescription')}</p>
              )}
            </CardContent>
          </Card>

          <p className="text-xs text-muted-foreground">
            <bdi>
              <Trans
                i18nKey="companies.createdBy"
                values={{ name: task.created_by_name ?? t('admin.audit.system'), when: fmt.dateTime(task.created_at) }}
                components={{ b: <bdi className="whitespace-nowrap" /> }}
              />
            </bdi>
            {' · '}
            <bdi>
              <Trans
                i18nKey="companies.updatedBy"
                values={{ name: task.updated_by_name ?? task.created_by_name ?? t('admin.audit.system'), when: fmt.relative(task.updated_at) }}
                components={{ b: <bdi className="whitespace-nowrap" /> }}
              />
            </bdi>
          </p>
        </div>
      )}
    </div>
  )
}
