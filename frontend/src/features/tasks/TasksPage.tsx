import { useQueryClient } from '@tanstack/react-query'
import { CalendarDays, List, Plus, Search, SquareKanban } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { FormDialog, PageHeader, SimpleSelect } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ALL } from '@/lib/contacts'
import { usePermission } from '@/lib/permissions'
import {
  loadLayout,
  QUICK_FILTERS,
  saveLayout,
  TASK_LAYOUTS,
  TASK_PRIORITIES,
  TASK_SORTS,
  TASK_STATUSES,
  useTaskAssignees,
  type QuickFilter,
  type TaskLayout,
} from '@/lib/tasks'
import { cn, useDebouncedValue } from '@/lib/utils'
import { TaskBoard } from './TaskBoard'
import { TaskCalendar } from './TaskCalendar'
import { TaskForm } from './TaskForm'
import { TaskList } from './TaskList'

const VIEWS = Object.keys(QUICK_FILTERS) as QuickFilter[]
const LAYOUT_ICONS = { list: List, board: SquareKanban, calendar: CalendarDays }

/** Tasks: one set of quick filters and filters shared by the List, Board and Calendar views. */
export function TasksPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const canCreate = usePermission('tasks.create')
  const people = useTaskAssignees()

  const view: QuickFilter = VIEWS.includes(params.get('view') as QuickFilter) ? (params.get('view') as QuickFilter) : 'mine'
  const creating = params.get('new') === '1'
  const newDue = params.get('due') ?? undefined
  const [layout, setLayoutState] = useState<TaskLayout>(loadLayout)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState(ALL)
  const [priority, setPriority] = useState(ALL)
  const [assignee, setAssignee] = useState(ALL)
  const [sort, setSort] = useState('default')
  const [page, setPage] = useState(1)
  const q = useDebouncedValue(search.trim())

  const setLayout = (l: TaskLayout) => {
    setLayoutState(l)
    saveLayout(l)
  }
  const reset = <T,>(setter: (v: T) => void) => (v: T) => {
    setter(v)
    setPage(1)
  }
  const keep: Record<string, string> = view === 'mine' ? {} : { view }
  const setView = (v: QuickFilter) => {
    setPage(1)
    setParams(v === 'mine' ? {} : { view: v }, { replace: true })
  }
  const openCreate = (due?: string) => setParams(due ? { ...keep, new: '1', due } : { ...keep, new: '1' })
  const closeCreate = () => setParams(keep, { replace: true })

  // The same filters feed every view (the board ignores status: its columns are the statuses).
  const filters: Record<string, string | undefined> = {
    ...QUICK_FILTERS[view],
    search: q || undefined,
    status: status === ALL || layout === 'board' ? undefined : status,
    priority: priority === ALL ? undefined : priority,
    assigned_to: assignee === ALL ? undefined : assignee,
  }
  const filtered = q !== '' || status !== ALL || priority !== ALL || assignee !== ALL

  return (
    <>
      <PageHeader
        title={t('tasks.title')}
        subtitle={t('tasks.subtitle')}
        actions={
          canCreate && (
            <Button onClick={() => openCreate()}>
              <Plus className="size-4" />
              {t('tasks.add')}
            </Button>
          )
        }
      />

      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label={t('tasks.views.label')} className="flex max-w-full gap-1 overflow-x-auto rounded-lg bg-muted p-1">
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
        <div role="radiogroup" aria-label={t('tasks.layouts.label')} className="flex gap-1 rounded-lg border p-1">
          {TASK_LAYOUTS.map((l) => {
            const Icon = LAYOUT_ICONS[l]
            return (
              <button
                key={l}
                type="button"
                role="radio"
                aria-checked={layout === l}
                onClick={() => setLayout(l)}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm transition-colors',
                  layout === l ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )}
              >
                <Icon className="size-4" />
                {t(`tasks.layouts.${l}`)}
              </button>
            )
          })}
        </div>
      </div>

      <div
        className={cn(
          'mb-4 grid grid-cols-2 gap-2',
          layout === 'list'
            ? 'lg:grid-cols-[minmax(0,1fr)_10rem_10rem_12rem_11rem]'
            : layout === 'board'
              ? 'lg:grid-cols-[minmax(0,1fr)_10rem_12rem]'
              : 'lg:grid-cols-[minmax(0,1fr)_10rem_10rem_12rem]',
        )}
      >
        <div className="relative col-span-2 lg:col-span-1">
          <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => reset(setSearch)(e.target.value)}
            placeholder={t('tasks.searchPlaceholder')}
            className="ps-8"
            aria-label={t('tasks.searchPlaceholder')}
          />
        </div>
        {layout !== 'board' && (
          <SimpleSelect
            value={status}
            onChange={reset(setStatus)}
            options={[{ value: ALL, label: t('tasks.allStatuses') }, ...TASK_STATUSES.map((s) => ({ value: s, label: t(`tasks.statuses.${s}`) }))]}
          />
        )}
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
        {layout === 'list' && (
          <SimpleSelect value={sort} onChange={reset(setSort)} options={TASK_SORTS.map((s) => ({ value: s, label: t(`tasks.sorts.${s}`) }))} />
        )}
      </div>

      {layout === 'list' && (
        <TaskList
          params={{ ...filters, ordering: sort === 'default' ? undefined : sort }}
          page={page}
          onPage={setPage}
          empty={{
            title: t(filtered ? 'tasks.emptyFiltered' : `tasks.empty.${view}`),
            hint: !filtered && canCreate && view !== 'overdue' ? t('tasks.emptyHint') : undefined,
          }}
        />
      )}
      {layout === 'board' && (
        <TaskBoard
          params={filters}
          onShowAllDone={() => {
            setStatus('done')
            setLayout('list')
            setPage(1)
          }}
        />
      )}
      {layout === 'calendar' && <TaskCalendar params={filters} onCreate={(date) => openCreate(date)} />}

      {creating && canCreate && (
        <FormDialog open onOpenChange={(o) => !o && closeCreate()} title={t('tasks.add')}>
          <TaskForm
            defaultDueDate={newDue}
            onCancel={closeCreate}
            onSaved={(task) => {
              void queryClient.invalidateQueries({ queryKey: ['tasks'] })
              toast.success(t('tasks.created'))
              if (layout === 'list') navigate(`/tasks/${task.id}`, { replace: true })
              else closeCreate() // stay on the board or calendar, where the new task now shows
            }}
          />
        </FormDialog>
      )}
    </>
  )
}
