import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, CopyPlus, Pencil, Plus, Target, TrendingUp } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, FormDialog, FormField, PageHeader, SimpleSelect } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { addDays, todayInOffice, weekStartOf } from '@/lib/bookings'
import { useConfirm } from '@/lib/confirm'
import { useFormat } from '@/lib/format'
import { GOAL_BAR, GOAL_TONE, goalState, PLANNING_KEY, useGoalHistory, useWeekGoals, type WeeklyGoal } from '@/lib/planning'
import { useDepartments, useUserOptions } from '@/lib/queries'
import { cn } from '@/lib/utils'

function useRefresh() {
  const queryClient = useQueryClient()
  return () => void queryClient.invalidateQueries({ queryKey: PLANNING_KEY })
}

/** Weekly plan: each team's goals for the week with progress; managers plan their department, admins everyone's. */
export function PlanningPage() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const me = useMe()
  const refresh = useRefresh()
  const [params, setParams] = useSearchParams()
  const today = todayInOffice(fmt.settings.timezone)
  const thisWeek = weekStartOf(today, fmt.settings.week_start)
  const week = weekStartOf(params.get('week') || today, fmt.settings.week_start)
  const isAdmin = me.role === 'admin'
  const [department, setDepartment] = useState('')
  const { data: departments } = useDepartments()
  const { data, isLoading, isError, refetch } = useWeekGoals(week, department)
  const [editing, setEditing] = useState<WeeklyGoal | 'new' | null>(null)
  const goTo = (w: string) => setParams(w === thisWeek ? {} : { week: w }, { replace: true })
  const carry = useMutation({
    mutationFn: async () =>
      (await api.post<WeeklyGoal[]>('/planning/goals/carry-over/', isAdmin ? { week_start: week, all_departments: true } : { week_start: week, department: me.department })).data,
    onSuccess: (copies) => {
      refresh()
      toast.success(copies.length ? t('planning.carriedToast', { count: copies.length }) : t('planning.nothingToCarry'))
      if (copies.length) goTo(addDays(week, 7))
    },
    onError: (e) => toast.error(apiError(e).message),
  })
  const goals = data?.goals ?? []
  const groups = new Map<string, WeeklyGoal[]>()
  for (const g of goals) {
    const key = g.department_name ?? ''
    groups.set(key, [...(groups.get(key) ?? []), g])
  }
  const done = goals.filter((g) => g.done).length
  const average = goals.length ? Math.round((goals.reduce((s, g) => s + Math.min(1, g.current / g.target), 0) / goals.length) * 100) : 0
  const canCarry = data?.can_plan && week <= thisWeek && goals.some((g) => !g.done && g.can_edit)
  return (
    <>
      <PageHeader
        title={t('planning.title')}
        subtitle={t('planning.subtitle')}
        actions={
          data?.can_plan && week >= thisWeek ? (
            <Button onClick={() => setEditing('new')}>
              <Plus className="size-4" />
              {t('planning.addGoal')}
            </Button>
          ) : undefined
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Button variant="outline" size="icon" aria-label={t('planning.previousWeek')} onClick={() => goTo(addDays(week, -7))}>
          <ChevronLeft className="size-4 rtl:rotate-180" />
        </Button>
        <span className="min-w-44 text-center text-sm font-medium">
          <bdi dir="ltr" className="font-latin">{fmt.date(`${week}T12:00:00`)} – {fmt.date(`${addDays(week, 6)}T12:00:00`)}</bdi>
        </span>
        <Button variant="outline" size="icon" aria-label={t('planning.nextWeek')} onClick={() => goTo(addDays(week, 7))}>
          <ChevronRight className="size-4 rtl:rotate-180" />
        </Button>
        {week !== thisWeek && (
          <Button variant="ghost" size="sm" onClick={() => goTo(thisWeek)}>{t('planning.thisWeek')}</Button>
        )}
        {isAdmin && (
          <div className="w-48">
            <SimpleSelect
              id="plan-dept"
              value={department}
              onChange={setDepartment}
              options={[
                { value: '', label: t('planning.allTeams') },
                { value: 'office', label: t('planning.wholeOffice') },
                ...(departments ?? []).map((d) => ({ value: String(d.id), label: d.name })),
              ]}
            />
          </div>
        )}
        {canCarry && (
          <Button variant="outline" size="sm" className="ms-auto" disabled={carry.isPending} onClick={() => carry.mutate()}>
            <CopyPlus className="size-4" />
            {t('planning.carryOver')}
          </Button>
        )}
      </div>
      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading || !data ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : !goals.length ? (
        <EmptyState icon={Target} title={t('planning.noGoals')} hint={data.can_plan ? t('planning.noGoalsHint') : undefined} className="py-12" />
      ) : (
        <div className="grid gap-4">
          <div className="grid grid-cols-2 gap-3 sm:max-w-md">
            <Card className="gap-1 py-3">
              <CardContent className="px-4">
                <p className="text-xs text-muted-foreground">{t('planning.goalsDone')}</p>
                <p className="mt-1 text-lg font-semibold"><span className="font-latin">{done}</span> / <span className="font-latin">{goals.length}</span></p>
              </CardContent>
            </Card>
            <Card className="gap-1 py-3">
              <CardContent className="px-4">
                <p className="text-xs text-muted-foreground">{t('planning.averageProgress')}</p>
                <p className="mt-1 font-latin text-lg font-semibold">{average}%</p>
              </CardContent>
            </Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            {[...groups.entries()].map(([name, list]) => (
              <Card key={name} className="gap-3">
                <CardHeader className="flex flex-row items-center gap-2">
                  <TrendingUp className="size-4 text-muted-foreground" />
                  <CardTitle className="flex-1 text-sm font-medium">{name ? <bdi>{name}</bdi> : t('planning.wholeOffice')}</CardTitle>
                  <span className="text-xs text-muted-foreground">
                    {t('planning.doneOf', { done: list.filter((g) => g.done).length, total: list.length })}
                  </span>
                </CardHeader>
                <CardContent>
                  <ul className="grid gap-3">
                    {list.map((g) => (
                      <GoalRow key={g.id} goal={g} today={today} onEdit={() => setEditing(g)} />
                    ))}
                  </ul>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
      {editing && <GoalDialog goal={editing === 'new' ? undefined : editing} week={week < thisWeek ? thisWeek : week} onClose={() => setEditing(null)} />}
    </>
  )
}

function GoalRow({ goal: g, today, onEdit }: { goal: WeeklyGoal; today: string; onEdit: () => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const [recording, setRecording] = useState(false)
  const state = goalState(g, today, fmt.settings.working_days)
  const share = Math.min(100, (g.current / g.target) * 100)
  return (
    <li className="grid gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 font-medium [unicode-bidi:plaintext]">{g.title}</span>
        {g.carried_from && <Badge variant="secondary" className="font-normal">{t('planning.carried')}</Badge>}
        <Badge variant="outline" className={cn('font-normal', GOAL_TONE[state])}>{t(`planning.state.${state}`)}</Badge>
      </div>
      <div className="flex items-center gap-2">
        <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={g.current} aria-valuemin={0} aria-valuemax={g.target} aria-label={g.title}>
          <div className={cn('h-full rounded-full', GOAL_BAR[state])} style={{ width: `${share}%` }} />
        </div>
        <span className="shrink-0 text-sm">
          <span className="font-latin font-medium">{g.current}</span>
          <span className="text-muted-foreground"> / <span className="font-latin">{g.target}</span>{g.unit && <> <bdi>{g.unit}</bdi></>}</span>
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
        <span>{g.owner_name ? <bdi>{g.owner_name}</bdi> : t('planning.noOwner')}</span>
        {g.description && <span className="min-w-0 truncate [unicode-bidi:plaintext]">· {g.description}</span>}
        <span className="flex-1" />
        {g.can_record && (
          <Button variant="outline" size="xs" onClick={() => setRecording(true)}>{t('planning.record')}</Button>
        )}
        {g.can_edit && (
          <Button variant="ghost" size="icon-xs" onClick={onEdit} aria-label={t('planning.editGoal', { title: g.title })}>
            <Pencil className="size-3.5" />
          </Button>
        )}
      </div>
      {recording && <ProgressDialog goal={g} onClose={() => setRecording(false)} />}
    </li>
  )
}

function ProgressDialog({ goal, onClose }: { goal: WeeklyGoal; onClose: () => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const refresh = useRefresh()
  const [value, setValue] = useState(String(goal.current))
  const [note, setNote] = useState('')
  const history = useGoalHistory(goal.id)
  const save = useMutation({
    mutationFn: async (body: { value?: number; add?: number }) => api.post(`/planning/goals/${goal.id}/progress/`, { ...body, note }),
    onSuccess: () => {
      refresh()
      toast.success(t('planning.progressSaved'))
      onClose()
    },
    onError: (e) => toast.error(Object.values(apiError(e).fields)[0] ?? apiError(e).message),
  })
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={goal.title}
      description={t('planning.progressOf', { current: goal.current, target: goal.target, unit: goal.unit })}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="outline" disabled={save.isPending} onClick={() => save.mutate({ add: 1 })}>{t('planning.addOne')}</Button>
          <Button disabled={save.isPending || value === '' || Number(value) < 0} onClick={() => save.mutate({ value: Number(value) })}>{t('common.save')}</Button>
        </>
      }
    >
      <div className="grid gap-4">
        <FormField id="gp-value" label={t('planning.progressNow', { unit: goal.unit || t('planning.units') })}>
          <Input id="gp-value" type="number" min={0} value={value} onChange={(e) => setValue(e.target.value)} className="font-latin sm:w-40" />
        </FormField>
        <FormField id="gp-note" label={t('planning.note')}>
          <Input id="gp-note" value={note} dir="auto" maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder={t('planning.notePlaceholder')} />
        </FormField>
        <div className="grid gap-1.5">
          <p className="text-sm font-medium">{t('planning.history')}</p>
          {history.isLoading ? (
            <Skeleton className="h-12" />
          ) : !history.data?.length ? (
            <p className="text-sm text-muted-foreground">{t('planning.noHistory')}</p>
          ) : (
            <ul className="max-h-44 divide-y overflow-y-auto rounded-md border text-sm">
              {history.data.map((h) => (
                <li key={h.id} className="flex flex-wrap items-center gap-x-2 px-2.5 py-1.5">
                  <bdi dir="ltr" className="font-latin">{h.before} → {h.after}</bdi>
                  {h.note && <span className="min-w-0 truncate text-xs text-muted-foreground [unicode-bidi:plaintext]">{h.note}</span>}
                  <span className="ms-auto text-xs text-muted-foreground">
                    {h.by_name && <bdi>{h.by_name}</bdi>} · {fmt.dateTime(h.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </FormDialog>
  )
}

function GoalDialog({ goal, week, onClose }: { goal?: WeeklyGoal; week: string; onClose: () => void }) {
  const { t } = useTranslation()
  const me = useMe()
  const refresh = useRefresh()
  const confirm = useConfirm()
  const isAdmin = me.role === 'admin'
  const { data: departments } = useDepartments()
  const { data: users } = useUserOptions()
  const [form, setForm] = useState({
    title: goal?.title ?? '',
    description: goal?.description ?? '',
    department: goal ? (goal.department === null ? '' : String(goal.department)) : String(me.department ?? ''),
    owner: goal?.owner ? String(goal.owner) : '',
    target: String(goal?.target ?? 1),
    unit: goal?.unit ?? '',
    week_start: goal?.week_start ?? week,
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }))
  const people = (users ?? []).filter((u) => !form.department || String(u.department) === form.department)
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        title: form.title, description: form.description, department: form.department ? Number(form.department) : null,
        owner: form.owner ? Number(form.owner) : null, target: Number(form.target), unit: form.unit, week_start: form.week_start,
      }
      return goal ? api.patch(`/planning/goals/${goal.id}/`, body) : api.post('/planning/goals/', body)
    },
    onSuccess: () => {
      refresh()
      toast.success(t('common.saved'))
      onClose()
    },
    onError: (e) => {
      const err = apiError(e)
      setErrors(err.fields)
      toast.error(Object.values(err.fields)[0] ?? err.message)
    },
  })
  const remove = useMutation({
    mutationFn: async () => api.delete(`/planning/goals/${goal!.id}/`),
    onSuccess: () => {
      refresh()
      toast.success(t('common.deleted'))
      onClose()
    },
    onError: (e) => toast.error(apiError(e).message),
  })
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={goal ? t('planning.editGoal', { title: goal.title }) : t('planning.addGoal')}
      footer={
        <>
          {goal && (
            <Button
              variant="ghost"
              className="me-auto text-destructive"
              disabled={remove.isPending}
              onClick={async () => {
                if (await confirm({ title: t('planning.deleteTitle'), description: t('planning.deleteText'), confirmLabel: t('common.delete'), destructive: true }))
                  remove.mutate()
              }}
            >
              {t('common.delete')}
            </Button>
          )}
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !form.title.trim() || Number(form.target) < 1}>{t('common.save')}</Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField id="gl-title" label={t('planning.goal')} error={errors.title} className="sm:col-span-2">
          <Input id="gl-title" value={form.title} dir="auto" maxLength={160} onChange={(e) => set('title', e.target.value)} placeholder={t('planning.goalPlaceholder')} />
        </FormField>
        <FormField id="gl-target" label={t('planning.target')} error={errors.target}>
          <Input id="gl-target" type="number" min={1} value={form.target} onChange={(e) => set('target', e.target.value)} className="font-latin" />
        </FormField>
        <FormField id="gl-unit" label={t('planning.unit')} hint={t('planning.unitHint')}>
          <Input id="gl-unit" value={form.unit} dir="auto" maxLength={40} onChange={(e) => set('unit', e.target.value)} />
        </FormField>
        {isAdmin && (
          <FormField id="gl-dept" label={t('planning.team')} error={errors.department}>
            <SimpleSelect
              id="gl-dept"
              value={form.department}
              onChange={(v) => setForm((f) => ({ ...f, department: v, owner: '' }))}
              options={[{ value: '', label: t('planning.wholeOffice') }, ...(departments ?? []).map((d) => ({ value: String(d.id), label: d.name }))]}
            />
          </FormField>
        )}
        <FormField id="gl-owner" label={t('planning.owner')} error={errors.owner}>
          <SimpleSelect
            id="gl-owner"
            value={form.owner}
            onChange={(v) => set('owner', v)}
            options={[{ value: '', label: t('planning.noOwner') }, ...people.map((u) => ({ value: String(u.id), label: u.full_name }))]}
          />
        </FormField>
        <FormField id="gl-week" label={t('planning.week')} hint={t('planning.weekHint')} error={errors.week_start}>
          <Input id="gl-week" type="date" value={form.week_start} onChange={(e) => e.target.value && set('week_start', e.target.value)} className="font-latin" />
        </FormField>
        <FormField id="gl-desc" label={t('planning.details')} className="sm:col-span-2">
          <Textarea id="gl-desc" value={form.description} dir="auto" maxLength={1000} onChange={(e) => set('description', e.target.value)} className="min-h-16" />
        </FormField>
      </div>
    </FormDialog>
  )
}
