import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Ban, Check, CheckCircle2, ChevronLeft, ChevronRight, CheckSquare, ClipboardPen, LogIn, LogOut, MapPin, Pencil, Plus, Users, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, FormDialog, FormField, PageHeader, SimpleSelect } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { addDays, officeParts, todayInOffice, weekStartOf } from '@/lib/bookings'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { cn } from '@/lib/utils'
import { REPORT_TONE, useVisit, useVisitPeople, useVisits, VISIT_TONE, VISITS_KEY, visitRecordLink, type Visit } from '@/lib/visits'
import { CheckDialog, CheckList } from './CheckDialog'
import { ReportDialog, ReportView } from './ReportDialog'
import { VisitDialog } from './VisitDialog'

type Tab = 'mine' | 'past' | 'team' | 'approvals'

function useRefresh() {
  const queryClient = useQueryClient()
  return () => {
    for (const key of [VISITS_KEY, ['timeline'], ['calendar'], ['dashboard'], ['attendance']]) void queryClient.invalidateQueries({ queryKey: key })
  }
}

/** Field visits: mine (upcoming and past), my team's week and requests to decide (managers, admins). */
export function VisitsPage() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const [params, setParams] = useSearchParams()
  const canManage = usePermission('visits.delete')
  const asked = params.get('tab') as Tab | null
  const tab: Tab = asked === 'past' || (canManage && (asked === 'team' || asked === 'approvals')) ? asked : 'mine'
  const openId = Number(params.get('visit')) || null
  const [planning, setPlanning] = useState(false)
  const set = (changes: Record<string, string | undefined>) =>
    setParams((p) => {
      for (const [k, v] of Object.entries(changes)) {
        if (v) p.set(k, v)
        else p.delete(k)
      }
      return p
    }, { replace: true })
  const today = todayInOffice(fmt.settings.timezone)
  return (
    <>
      <PageHeader
        title={t('visits.title')}
        subtitle={t('visits.subtitle')}
        actions={
          <Button onClick={() => setPlanning(true)}>
            <Plus className="size-4" />
            {t('visits.plan')}
          </Button>
        }
      />
      <Tabs value={tab} onValueChange={(v) => set({ tab: v === 'mine' ? undefined : String(v) })} className="mb-4">
        <TabsList>
          <TabsTrigger value="mine">{t('visits.tabs.mine')}</TabsTrigger>
          <TabsTrigger value="past">{t('visits.tabs.past')}</TabsTrigger>
          {canManage && <TabsTrigger value="team">{t('visits.tabs.team')}</TabsTrigger>}
          {canManage && <TabsTrigger value="approvals">{t('visits.tabs.approvals')}</TabsTrigger>}
        </TabsList>
      </Tabs>
      {tab === 'team' ? (
        <TeamWeek week={weekStartOf(params.get('week') || today, fmt.settings.week_start)} onWeek={(w) => set({ week: w })} />
      ) : (
        <VisitList query={tab === 'approvals' ? { scope: 'approvals' } : { scope: 'mine', when: tab === 'past' ? 'past' : 'upcoming' }}
          empty={t(tab === 'approvals' ? 'visits.nothingToApprove' : tab === 'past' ? 'visits.noPast' : 'visits.noUpcoming')}
          showPerson={tab === 'approvals'} />
      )}
      {planning && <VisitDialog onClose={() => setPlanning(false)} />}
      {openId && <VisitDetails id={openId} onClose={() => set({ visit: undefined })} />}
    </>
  )
}

function TeamWeek({ week, onWeek }: { week: string; onWeek: (w: string) => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const { data: people } = useVisitPeople()
  const [person, setPerson] = useState('')
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="icon" aria-label={t('planning.previousWeek')} onClick={() => onWeek(addDays(week, -7))}>
          <ChevronLeft className="size-4 rtl:rotate-180" />
        </Button>
        <span className="min-w-44 text-center text-sm font-medium">
          <bdi dir="ltr" className="font-latin">{fmt.date(`${week}T12:00:00`)} – {fmt.date(`${addDays(week, 6)}T12:00:00`)}</bdi>
        </span>
        <Button variant="outline" size="icon" aria-label={t('planning.nextWeek')} onClick={() => onWeek(addDays(week, 7))}>
          <ChevronRight className="size-4 rtl:rotate-180" />
        </Button>
        <div className="w-52">
          <SimpleSelect id="visit-person" value={person} onChange={setPerson}
            options={[{ value: '', label: t('visits.everyone') }, ...(people?.plan_for ?? []).map((p) => ({ value: String(p.id), label: p.name }))]} />
        </div>
      </div>
      <VisitList query={{ scope: 'team', from: week, to: addDays(week, 6), ...(person ? { person } : {}) }} empty={t('visits.noTeam')} showPerson />
    </div>
  )
}

function VisitList({ query, empty, showPerson }: { query: Parameters<typeof useVisits>[0]; empty: string; showPerson?: boolean }) {
  const fmt = useFormat()
  const { data, isLoading, isError, refetch } = useVisits(query)
  if (isError) return <ErrorState onRetry={() => void refetch()} />
  if (isLoading || !data) return <Skeleton className="h-48 rounded-xl" />
  if (!data.length) return <EmptyState icon={MapPin} title={empty} className="py-12" />
  const days = new Map<string, Visit[]>()
  for (const v of data) {
    const day = officeParts(fmt.settings.timezone, v.start).date
    days.set(day, [...(days.get(day) ?? []), v])
  }
  return (
    <div className="grid gap-5">
      {[...days.entries()].map(([day, visits]) => (
        <section key={day}>
          <h2 className="mb-2 text-sm font-medium text-muted-foreground">{fmt.date(`${day}T12:00:00`)}</h2>
          <ul className="grid gap-2">
            {visits.map((v) => <VisitRow key={v.id} visit={v} showPerson={showPerson} />)}
          </ul>
        </section>
      ))}
    </div>
  )
}

function VisitRow({ visit: v, showPerson }: { visit: Visit; showPerson?: boolean }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const [, setParams] = useSearchParams()
  const recordLink = visitRecordLink(v)
  const [now] = useState(() => Date.now())
  const overdue = v.status === 'planned' && new Date(v.end).getTime() < now
  return (
    <li>
      <Card className="gap-2 py-3">
        <CardContent className="flex flex-wrap items-start gap-3 px-4">
          <span className="min-w-32 shrink-0 whitespace-nowrap pt-0.5 text-sm font-medium">{fmt.time(v.start)}–{fmt.time(v.end)}</span>
          <div className="min-w-0 flex-1 basis-56">
            <p className="flex flex-wrap items-center gap-2">
              <button type="button" className="text-start font-medium hover:underline [unicode-bidi:plaintext]"
                onClick={() => setParams((p) => { p.set('visit', String(v.id)); return p }, { replace: true })}>
                {v.title}
              </button>
              <Badge variant="outline" className={cn('font-normal', VISIT_TONE[v.status])}>{t(`visits.status.${v.status}`)}</Badge>
              {v.checks.some((c) => c.user === v.assigned_to) && v.status === 'planned' && (
                <Badge variant="outline" className="border-emerald-500/50 font-normal text-emerald-700 dark:text-emerald-300">
                  {v.checks.find((c) => c.user === v.assigned_to)?.checked_out_at ? t('visits.checks.left') : t('visits.checks.arrived')}
                </Badge>
              )}
              {v.report && <Badge variant="outline" className={cn('font-normal', REPORT_TONE[v.report.outcome])}>{t(`visits.report.outcomes.${v.report.outcome}`)}</Badge>}
              {overdue && <Badge variant="outline" className="border-amber-500/50 font-normal text-amber-700 dark:text-amber-300">{t('visits.notClosed')}</Badge>}
            </p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {recordLink ? <Link to={recordLink} className="text-primary hover:underline"><bdi>{v.place}</bdi></Link> : <bdi>{v.place}</bdi>}
              {' · '}{t(`visits.purposes.${v.purpose}`)}
              {(v.address || v.city) && <> · <span className="[unicode-bidi:plaintext]">{[v.address, v.city].filter(Boolean).join(', ')}</span></>}
            </p>
            {(showPerson || v.companions.length > 0) && (
              <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
                <Users className="size-3.5" />
                <bdi>{[v.assigned_to_name, ...v.companions.map((c) => c.name)].join(', ')}</bdi>
              </p>
            )}
          </div>
          <VisitActions visit={v} />
        </CardContent>
      </Card>
    </li>
  )
}

function VisitActions({ visit: v, onDone }: { visit: Visit; onDone?: () => void }) {
  const { t } = useTranslation()
  const refresh = useRefresh()
  const { user } = useAuth()
  const [mode, setMode] = useState<'edit' | 'close' | 'cancel' | 'reject' | 'in' | 'out' | 'report' | null>(null)
  const mine = v.checks.find((c) => c.user === user?.id)
  const canCheckOut = v.status === 'planned' && !!mine && !mine.checked_out_at
  const approve = useMutation({
    mutationFn: async () => api.post(`/visits/${v.id}/decide/`, { approve: true }),
    onSuccess: () => {
      refresh()
      toast.success(t('visits.approvedToast'))
      onDone?.()
    },
    onError: (e) => toast.error(apiError(e).message),
  })
  if (!(v.can_change || v.can_close || v.can_decide || v.can_check_in || canCheckOut || v.can_report)) return null
  return (
    <div className="flex flex-wrap gap-2">
      {v.can_check_in && <Button size="sm" onClick={() => setMode('in')}><LogIn className="size-4 rtl:rotate-180" />{t('visits.checks.checkIn')}</Button>}
      {canCheckOut && <Button size="sm" variant="outline" onClick={() => setMode('out')}><LogOut className="size-4 rtl:rotate-180" />{t('visits.checks.checkOut')}</Button>}
      {v.can_decide && (
        <>
          <Button variant="outline" size="sm" onClick={() => setMode('reject')}><X className="size-4" />{t('visits.reject')}</Button>
          <Button size="sm" disabled={approve.isPending} onClick={() => approve.mutate()}><Check className="size-4" />{t('visits.approve')}</Button>
        </>
      )}
      {v.can_report && (
        <Button size="sm" variant={v.report ? 'outline' : 'default'} onClick={() => setMode('report')}>
          <ClipboardPen className="size-4" />{t(v.report ? 'visits.report.edit' : 'visits.report.write')}
        </Button>
      )}
      {v.can_close && (
        <Button size="sm" variant="outline" onClick={() => setMode('close')}><CheckCircle2 className="size-4" />{t('visits.markDone')}</Button>
      )}
      {v.can_change && (
        <>
          <Button variant="ghost" size="icon-sm" onClick={() => setMode('edit')} aria-label={t('visits.editTitle')}><Pencil className="size-4" /></Button>
          <Button variant="ghost" size="icon-sm" className="text-destructive" onClick={() => setMode('cancel')} aria-label={t('visits.cancel')}><Ban className="size-4" /></Button>
        </>
      )}
      {(mode === 'in' || mode === 'out') && <CheckDialog visit={v} mode={mode} onClose={() => setMode(null)} />}
      {mode === 'report' && <ReportDialog visit={v} onClose={() => setMode(null)} />}
      {mode === 'edit' && <VisitDialog visit={v} onClose={() => setMode(null)} />}
      {(mode === 'close' || mode === 'cancel' || mode === 'reject') && (
        <NoteDialog visit={v} mode={mode} onClose={() => setMode(null)} onDone={onDone} />
      )}
    </div>
  )
}

function NoteDialog({ visit, mode, onClose, onDone }: { visit: Visit; mode: 'close' | 'cancel' | 'reject'; onClose: () => void; onDone?: () => void }) {
  const { t } = useTranslation()
  const refresh = useRefresh()
  const [note, setNote] = useState('')
  const send = useMutation({
    mutationFn: async () =>
      mode === 'reject' ? api.post(`/visits/${visit.id}/decide/`, { approve: false, note }) : api.post(`/visits/${visit.id}/${mode}/`, { note }),
    onSuccess: () => {
      refresh()
      toast.success(t(`visits.${mode}Toast`))
      onClose()
      onDone?.()
    },
    onError: (e) => toast.error(Object.values(apiError(e).fields)[0] ?? apiError(e).message),
  })
  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={t(`visits.${mode}Title`, { title: visit.title })}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant={mode === 'close' ? 'default' : 'destructive'} disabled={send.isPending} onClick={() => send.mutate()}>{t(`visits.${mode}Confirm`)}</Button>
        </>
      }>
      <FormField id="vs-note" label={t(`visits.${mode}Note`)}>
        <Textarea id="vs-note" value={note} dir="auto" maxLength={300} onChange={(e) => setNote(e.target.value)} className="min-h-16" />
      </FormField>
    </FormDialog>
  )
}

/** One visit in full (opened from the calendar, a timeline or a notification). */
function VisitDetails({ id, onClose }: { id: number; onClose: () => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const { data: v, isError } = useVisit(id)
  const recordLink = v ? visitRecordLink(v) : null
  const rows: { label: string; value: React.ReactNode }[] = v
    ? [
        { label: t('visits.when'), value: <>{fmt.date(v.start)} · {fmt.time(v.start)}–{fmt.time(v.end)}</> },
        { label: t('visits.whoOrWhere'), value: recordLink ? <Link to={recordLink} className="text-primary hover:underline"><bdi>{v.place}</bdi></Link> : <bdi>{v.place}</bdi> },
        { label: t('visits.purpose'), value: t(`visits.purposes.${v.purpose}`) },
        { label: t('visits.address'), value: [v.address, v.city].filter(Boolean).join(', ') },
        { label: t('visits.who'), value: <bdi>{[v.assigned_to_name, ...v.companions.map((c) => c.name)].join(', ')}</bdi> },
        { label: t('visits.pinShort'), value: v.latitude && <bdi dir="ltr" className="font-latin">{v.latitude}, {v.longitude}</bdi> },
        { label: t('visits.checks.label'), value: (v.checks.length > 0 || v.status === 'planned') && <CheckList checks={v.checks} /> },
        { label: t('visits.report.label'), value: v.report && <ReportView report={v.report} /> },
        { label: t('visits.forTask'), value: v.task && <Link to={`/tasks/${v.task.id}`} className="inline-flex items-center gap-1 text-primary hover:underline"><CheckSquare className="size-3.5" /><bdi>{v.task.title}</bdi></Link> },
        { label: t('visits.notes'), value: v.notes && <span className="whitespace-pre-line [unicode-bidi:plaintext]">{v.notes}</span> },
        { label: t('visits.decision'), value: v.decided_by_name && <>{v.decided_by_name}{v.decision_note && <> · <span className="[unicode-bidi:plaintext]">{v.decision_note}</span></>}</> },
        { label: t('visits.closed'), value: v.closed_at && <>{v.closed_by_name} · {fmt.dateTime(v.closed_at)}{v.close_note && <> · <span className="[unicode-bidi:plaintext]">{v.close_note}</span></>}</> },
        { label: t('visits.plannedBy'), value: v.created_by_name },
      ]
    : []
  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={v?.title ?? t('visits.title')}>
      {isError ? (
        <p className="text-sm text-muted-foreground">{t('visits.notFound')}</p>
      ) : !v ? (
        <Skeleton className="h-40" />
      ) : (
        <div className="grid gap-3">
          <Badge variant="outline" className={cn('w-fit font-normal', VISIT_TONE[v.status])}>{t(`visits.status.${v.status}`)}</Badge>
          <dl className="grid gap-2 text-sm">
            {rows.filter((r) => r.value).map(({ label, value }) => (
              <div key={label} className="grid grid-cols-[7rem_1fr] gap-2">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="min-w-0 break-words">{value}</dd>
              </div>
            ))}
          </dl>
          <VisitActions visit={v} onDone={onClose} />
        </div>
      )}
    </FormDialog>
  )
}

