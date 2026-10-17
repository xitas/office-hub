import { Building2, Link2, UserRound, X } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { FormDialog, FormField, SimpleSelect, TextField } from '@/components/common'
import { RecordPicker, type Picked } from '@/components/common/RecordPicker'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import {
  shortTime,
  TASK_PRIORITIES,
  TASK_STATUSES,
  type RecurrenceInput,
  type Task,
  type TaskInput,
  type TaskPriority,
  type TaskStatus,
} from '@/lib/tasks'
import { AssigneePicker } from './AssigneePicker'
import { RepeatEditor } from './RepeatEditor'

export interface Linked {
  type: 'contact' | 'company'
  id: number
  name: string
}

/** Pre-filled values for a new task (e.g. "Create task from follow-up"). */
export interface TaskDefaults {
  title?: string
  description?: string
  linked?: Linked
  followUpOf?: number
}

type Scope = 'this' | 'future'

function ruleOf(task?: Task): RecurrenceInput | null {
  if (!task?.repeat?.active) return null
  const { frequency, interval, weekdays, monthly_mode, month_day, month_week, month_weekday, end_date, count } = task.repeat
  return { frequency, interval, weekdays, monthly_mode, month_day, month_week, month_weekday, end_date, count }
}

/** Create or edit a task. New tasks are assigned to you unless you pick other people. */
export function TaskForm({
  task,
  defaultDueDate,
  defaults,
  onSaved,
  onCancel,
}: {
  task?: Task
  /** New tasks: pre-fill the due date (e.g. the day clicked in the calendar). */
  defaultDueDate?: string
  defaults?: TaskDefaults
  onSaved: (task: Task) => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  const me = useMe()
  const [title, setTitle] = useState(task?.title ?? defaults?.title ?? '')
  const [description, setDescription] = useState(task?.description ?? defaults?.description ?? '')
  const [assignees, setAssignees] = useState<number[]>(task?.assignees ?? [me.id])
  const [dueDate, setDueDate] = useState(task?.due_date ?? defaultDueDate ?? '')
  const [dueTime, setDueTime] = useState(shortTime(task?.due_time ?? null))
  const [priority, setPriority] = useState<TaskPriority>(task?.priority ?? 'medium')
  const [status, setStatus] = useState<TaskStatus>(task?.status ?? 'todo')
  const [linked, setLinked] = useState<Linked | null>(
    task?.contact
      ? { type: 'contact', id: task.contact, name: task.contact_name ?? '' }
      : task?.company
        ? { type: 'company', id: task.company, name: task.company_name ?? '' }
        : (defaults?.linked ?? null),
  )
  const originalRule = useMemo(() => ruleOf(task), [task])
  const [rule, setRule] = useState<RecurrenceInput | null>(originalRule)
  // Saving a change to a repeating task first asks: this one, or this and the ones after it?
  const [askScope, setAskScope] = useState<TaskInput | null>(null)
  const [picking, setPicking] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)

  const pick = (p: Picked) => {
    // The picker here offers contacts and companies only.
    if ('contact' in p.target) setLinked({ type: 'contact', id: p.target.contact, name: p.name })
    else if ('company' in p.target) setLinked({ type: 'company', id: p.target.company, name: p.name })
    setPicking(false)
  }

  const ruleChanged = JSON.stringify(rule) !== JSON.stringify(originalRule)

  const save = async (body: TaskInput & { recurrence?: RecurrenceInput | null; scope?: Scope; follow_up_of?: number }) => {
    setAskScope(null)
    setSaving(true)
    setErrors({})
    setMessage('')
    try {
      const { data } = task ? await api.patch<Task>(`/tasks/${task.id}/`, body) : await api.post<Task>('/tasks/', body)
      onSaved(data)
    } catch (err) {
      const info = apiError(err)
      setErrors(info.fields)
      setMessage(Object.keys(info.fields).length ? '' : info.message)
    } finally {
      setSaving(false)
    }
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const body: TaskInput & { recurrence?: RecurrenceInput | null; scope?: Scope; follow_up_of?: number } = {
      title,
      description,
      assignees,
      due_date: dueDate || null,
      due_time: dueDate && dueTime ? dueTime : null,
      priority,
      status,
      contact: linked?.type === 'contact' ? linked.id : null,
      company: linked?.type === 'company' ? linked.id : null,
    }
    if (!task) {
      if (rule) body.recurrence = rule
      if (defaults?.followUpOf) body.follow_up_of = defaults.followUpOf
      return save(body)
    }
    if (ruleChanged) {
      // A new or changed rule applies from this occurrence on; switching it off stops the series.
      return save({ ...body, recurrence: rule, scope: 'future' })
    }
    if (task.repeat?.active) return setAskScope(body)
    return save(body)
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="grid gap-4">
      <TextField id="task-title" label={t('tasks.fields.title')} value={title} onChange={(e) => setTitle(e.target.value)} error={errors.title} maxLength={200} required autoFocus={!task} />
      <FormField id="task-description" label={t('tasks.fields.description')} error={errors.description}>
        <Textarea id="task-description" value={description} onChange={(e) => setDescription(e.target.value)} rows={4} className="min-h-24" />
      </FormField>
      <FormField id="task-assignees" label={t('tasks.fields.assignees')} error={errors.assignees} hint={t('tasks.assigneesHint')}>
        <AssigneePicker id="task-assignees" value={assignees} onChange={setAssignees} current={task?.assignee_details} invalid={!!errors.assignees} />
      </FormField>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField id="task-due" label={t('tasks.fields.dueDate')} error={errors.due_date}>
          <Input id="task-due" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} className="font-latin" />
        </FormField>
        <FormField id="task-time" label={t('tasks.fields.dueTime')} error={errors.due_time} hint={t('tasks.dueTimeHint')}>
          <Input id="task-time" type="time" value={dueTime} onChange={(e) => setDueTime(e.target.value)} disabled={!dueDate} className="font-latin" />
        </FormField>
        <FormField id="task-priority" label={t('tasks.fields.priority')} error={errors.priority}>
          <SimpleSelect
            id="task-priority"
            value={priority}
            onChange={(v) => setPriority(v as TaskPriority)}
            options={TASK_PRIORITIES.map((p) => ({ value: p, label: t(`tasks.priorities.${p}`) }))}
          />
        </FormField>
        <FormField id="task-status" label={t('tasks.fields.status')} error={errors.status}>
          <SimpleSelect
            id="task-status"
            value={status}
            onChange={(v) => setStatus(v as TaskStatus)}
            options={TASK_STATUSES.map((s) => ({ value: s, label: t(`tasks.statuses.${s}`) }))}
          />
        </FormField>
      </div>

      <RepeatEditor value={rule} onChange={setRule} dueDate={dueDate} idPrefix="task-repeat" error={errors.recurrence ?? errors.weekdays} />

      <FormField id="task-link" label={t('tasks.fields.relatedTo')} error={errors.contact ?? errors.company}>
        {linked ? (
          <div className="flex items-center gap-2 rounded-lg border bg-muted/30 px-2.5 py-2 text-sm">
            {linked.type === 'contact' ? <UserRound className="size-4 text-muted-foreground" /> : <Building2 className="size-4 text-muted-foreground" />}
            <bdi className="min-w-0 flex-1 truncate">{linked.name}</bdi>
            <Button type="button" variant="ghost" size="icon" className="size-7" onClick={() => setLinked(null)} aria-label={t('tasks.unlink')}>
              <X className="size-4" />
            </Button>
          </div>
        ) : picking ? (
          <div className="rounded-lg border p-3">
            <RecordPicker idPrefix="task-link" onPick={pick} />
            <Button type="button" variant="ghost" size="sm" className="mt-2" onClick={() => setPicking(false)}>
              {t('common.cancel')}
            </Button>
          </div>
        ) : (
          <Button id="task-link" type="button" variant="outline" className="justify-self-start" onClick={() => setPicking(true)}>
            <Link2 className="size-4" />
            {t('tasks.linkRecord')}
          </Button>
        )}
      </FormField>

      {message && <p className="text-sm text-destructive">{message}</p>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? t('common.saving') : task ? t('common.save') : t('tasks.create')}
        </Button>
      </div>
      {askScope && (
        <FormDialog open onOpenChange={(o) => !o && setAskScope(null)} title={t('tasks.repeat.scopeTitle')} description={t('tasks.repeat.scopeHint')}>
          <div className="grid gap-2">
            <Button type="button" variant="outline" className="justify-start" onClick={() => void save({ ...askScope, scope: 'this' })}>
              {t('tasks.repeat.scopeThis')}
            </Button>
            <Button type="button" className="justify-start" onClick={() => void save({ ...askScope, scope: 'future' })}>
              {t('tasks.repeat.scopeFuture')}
            </Button>
          </div>
        </FormDialog>
      )}
    </form>
  )
}
