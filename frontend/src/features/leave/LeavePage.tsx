import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Ban, Check, Palmtree, Pencil, Plus, Settings2, Users, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, FormDialog, FormField, PageHeader } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { addDays, todayInOffice } from '@/lib/bookings'
import { CALENDAR_KEY } from '@/lib/calendar'
import { useConfirm } from '@/lib/confirm'
import { useFormat } from '@/lib/format'
import {
  LEAVE_KEY,
  shortDays,
  typeName,
  useBalances,
  useLeaveRequests,
  useLeaveTypes,
  useTeamLeave,
  type LeaveBalance,
  type LeaveRequest,
  type LeaveType,
} from '@/lib/leave'
import { usePermission } from '@/lib/permissions'
import { cn } from '@/lib/utils'
import { LeaveRequestDialog } from './LeaveRequestDialog'

type Tab = 'mine' | 'team' | 'settings'

const STATUS_TONE: Record<LeaveRequest['status'], string> = {
  pending: 'border-amber-500/50 text-amber-700 dark:text-amber-300',
  approved: 'border-success/40 text-success',
  rejected: 'border-destructive/40 text-destructive',
  cancelled: 'text-muted-foreground',
}

/** Leave: my balances and requests; my team's requests to decide and who's off; leave types and allowances (admins). */
export function LeavePage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const canApprove = usePermission('leave.approve')
  const canManage = usePermission('leave.manage')
  const asked = params.get('tab')
  const tab: Tab = asked === 'team' || (asked === 'settings' && canManage) ? asked : 'mine'
  const [requesting, setRequesting] = useState(false)
  return (
    <>
      <PageHeader
        title={t('leave.title')}
        subtitle={t('leave.subtitle')}
        actions={
          <Button onClick={() => setRequesting(true)}>
            <Plus className="size-4" />
            {t('leave.request')}
          </Button>
        }
      />
      <Tabs value={tab} onValueChange={(v) => setParams(v === 'mine' ? {} : { tab: String(v) }, { replace: true })} className="mb-4">
        <TabsList>
          <TabsTrigger value="mine">{t('leave.tabs.mine')}</TabsTrigger>
          <TabsTrigger value="team">{t(canApprove ? 'leave.tabs.team' : 'leave.tabs.whoIsOff')}</TabsTrigger>
          {canManage && <TabsTrigger value="settings">{t('leave.tabs.settings')}</TabsTrigger>}
        </TabsList>
      </Tabs>
      {tab === 'mine' ? <MyLeave /> : tab === 'team' ? <TeamLeave canApprove={canApprove} canManage={canManage} /> : <LeaveSettings />}
      {requesting && <LeaveRequestDialog onClose={() => setRequesting(false)} />}
    </>
  )
}

function useYear() {
  const fmt = useFormat()
  return Number(todayInOffice(fmt.settings.timezone).slice(0, 4))
}

function Days({ value }: { value: string }) {
  const { t } = useTranslation()
  return <>{t('leave.days', { count: Number(value), days: shortDays(value) })}</>
}

function dateRange(fmt: ReturnType<typeof useFormat>, first: string, last: string) {
  const a = fmt.date(`${first}T12:00:00`)
  return first === last ? a : `${a} – ${fmt.date(`${last}T12:00:00`)}`
}

// ------------------------------------------------------------------ my leave

function MyLeave() {
  const { t, i18n } = useTranslation()
  const year = useYear()
  const { data: types } = useLeaveTypes()
  const balances = useBalances('mine', year)
  const requests = useLeaveRequests('mine', year)
  const byType = new Map((types ?? []).map((x) => [x.id, x]))
  return (
    <div className="grid gap-6">
      <section aria-label={t('leave.balances', { year })}>
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">{t('leave.balances', { year })}</h2>
        {balances.isLoading ? (
          <Skeleton className="h-24 rounded-xl" />
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {(balances.data ?? []).map((b) => {
              const lt = byType.get(b.leave_type)
              const share = b.limited && Number(b.allowance) ? Math.min(100, ((Number(b.used) + Number(b.pending)) / Number(b.allowance)) * 100) : 0
              return (
                <li key={b.leave_type}>
                  <Card className="gap-2 py-4">
                    <CardContent className="grid gap-2 px-4">
                      <div className="flex items-center gap-2">
                        <span className="min-w-0 flex-1 truncate font-medium">{lt ? typeName(lt, i18n.language) : ''}</span>
                        {lt && !lt.paid && <Badge variant="outline" className="font-normal">{t('leave.unpaid')}</Badge>}
                      </div>
                      {b.limited ? (
                        <>
                          <p className="text-2xl font-semibold">
                            <span className="font-latin">{shortDays(b.remaining)}</span>
                            <span className="ms-1 text-sm font-normal text-muted-foreground">{t('leave.leftOf', { total: shortDays(b.allowance) })}</span>
                          </p>
                          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                            <div className="h-full rounded-full bg-primary" style={{ width: `${share}%` }} />
                          </div>
                          <p className="text-xs text-muted-foreground">
                            {t('leave.usedPending', { used: shortDays(b.used), pending: shortDays(b.pending) })}
                          </p>
                        </>
                      ) : (
                        <p className="text-sm text-muted-foreground">{t('leave.noLimit', { used: shortDays(b.used) })}</p>
                      )}
                      {b.note && <p className="text-xs text-muted-foreground">{b.note}</p>}
                    </CardContent>
                  </Card>
                </li>
              )
            })}
          </ul>
        )}
      </section>
      <section>
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">{t('leave.myRequests')}</h2>
        {requests.isError ? (
          <ErrorState onRetry={() => void requests.refetch()} />
        ) : requests.isLoading ? (
          <Skeleton className="h-32 rounded-xl" />
        ) : !requests.data?.length ? (
          <EmptyState icon={Palmtree} title={t('leave.noRequests')} className="py-10" />
        ) : (
          <ul className="grid gap-2">
            {requests.data.map((r) => (
              <RequestRow key={r.id} req={r} />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function RequestRow({ req: r, showName = false }: { req: LeaveRequest; showName?: boolean }) {
  const { t, i18n } = useTranslation()
  const fmt = useFormat()
  const queryClient = useQueryClient()
  const confirm = useConfirm()
  const [rejecting, setRejecting] = useState(false)
  const [note, setNote] = useState('')
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: LEAVE_KEY })
    void queryClient.invalidateQueries({ queryKey: CALENDAR_KEY })
    void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
  }
  const act = useMutation({
    mutationFn: async (what: { cancel: true } | { approve: boolean; note?: string }) =>
      'cancel' in what ? (await api.post(`/leave/requests/${r.id}/cancel/`)).data : (await api.post(`/leave/requests/${r.id}/decide/`, what)).data,
    onSuccess: (_d, what) => {
      refresh()
      setRejecting(false)
      toast.success('cancel' in what ? t('leave.cancelledToast') : what.approve ? t('leave.approvedToast') : t('leave.rejectedToast'))
    },
    onError: (e) => toast.error(apiError(e).message),
  })
  const half = r.half_day ? ` · ${t(`leave.halfDays.${r.half_day}`)}` : ''
  return (
    <li>
      <Card className="gap-2 py-3">
        <CardContent className="flex flex-wrap items-center gap-3 px-4">
          <div className="min-w-0 flex-1 basis-64">
            <p className="flex flex-wrap items-center gap-2">
              {showName && <bdi className="font-medium">{r.user_name}</bdi>}
              <span className={cn(!showName && 'font-medium')}>{typeName(r, i18n.language)}</span>
              <Badge variant="outline" className={cn('font-normal', STATUS_TONE[r.status])}>
                {t(`leave.status.${r.status}`)}
              </Badge>
            </p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              <bdi dir="ltr" className="font-latin">{dateRange(fmt, r.start_date, r.end_date)}</bdi> · <Days value={r.days} />
              {half}
              {showName && r.department_name && <> · <bdi>{r.department_name}</bdi></>}
            </p>
            {r.reason && <p className="mt-1 text-sm [unicode-bidi:plaintext]">{r.reason}</p>}
            {r.decision_note && (
              <p className="mt-1 text-xs text-muted-foreground">{t('leave.decisionNote', { name: r.decided_by_name ?? '', note: r.decision_note })}</p>
            )}
            {rejecting && (
              <div className="mt-2 grid gap-2">
                <Textarea value={note} dir="auto" maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder={t('leave.rejectNote')} aria-label={t('leave.rejectNote')} className="min-h-14" />
                <div className="flex gap-2">
                  <Button size="sm" variant="destructive" disabled={act.isPending} onClick={() => act.mutate({ approve: false, note })}>
                    {t('leave.reject')}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setRejecting(false)}>
                    {t('common.cancel')}
                  </Button>
                </div>
              </div>
            )}
          </div>
          {!rejecting && (
            <div className="flex gap-2">
              {r.can_decide && (
                <>
                  <Button variant="outline" size="sm" disabled={act.isPending} onClick={() => setRejecting(true)}>
                    <X className="size-4" />
                    {t('leave.reject')}
                  </Button>
                  <Button size="sm" disabled={act.isPending} onClick={() => act.mutate({ approve: true })}>
                    <Check className="size-4" />
                    {t('leave.approve')}
                  </Button>
                </>
              )}
              {r.can_cancel && !r.can_decide && (
                <Button
                  variant="outline"
                  size="sm"
                  className="text-destructive"
                  disabled={act.isPending}
                  onClick={async () => {
                    if (await confirm({ title: t('leave.cancelTitle'), description: t('leave.cancelText'), confirmLabel: t('leave.cancel'), cancelLabel: t('leave.keep'), destructive: true }))
                      act.mutate({ cancel: true })
                  }}
                >
                  <Ban className="size-4" />
                  {t('leave.cancel')}
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </li>
  )
}

// ------------------------------------------------------------------ team

function TeamLeave({ canApprove, canManage }: { canApprove: boolean; canManage: boolean }) {
  const { t, i18n } = useTranslation()
  const fmt = useFormat()
  const year = useYear()
  const today = todayInOffice(fmt.settings.timezone)
  const approvals = useLeaveRequests('approvals', year, canApprove)
  const off = useTeamLeave(today, addDays(today, 30))
  const balances = useBalances('team', year, canApprove)
  const { data: types } = useLeaveTypes()
  const [editing, setEditing] = useState<LeaveBalance | null>(null)
  const limited = (types ?? []).filter((x) => x.days_per_year !== null)
  const people = [...new Map((balances.data ?? []).map((b) => [b.user, b.user_name])).entries()]
  return (
    <div className="grid gap-6">
      {canApprove && (
        <section>
          <h2 className="mb-2 text-sm font-medium text-muted-foreground">{t('leave.toApprove')}</h2>
          {approvals.isLoading ? (
            <Skeleton className="h-24 rounded-xl" />
          ) : !approvals.data?.length ? (
            <p className="rounded-xl border bg-card p-4 text-sm text-muted-foreground">{t('leave.nothingToApprove')}</p>
          ) : (
            <ul className="grid gap-2">
              {approvals.data.map((r) => (
                <RequestRow key={r.id} req={r} showName />
              ))}
            </ul>
          )}
        </section>
      )}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2">
          <Users className="size-4 text-muted-foreground" />
          <CardTitle className="text-sm font-medium">{t('leave.whoIsOff')}</CardTitle>
        </CardHeader>
        <CardContent>
          {off.isLoading ? (
            <Skeleton className="h-16" />
          ) : !off.data?.length ? (
            <p className="text-sm text-muted-foreground">{t('leave.nobodyOff')}</p>
          ) : (
            <ul className="divide-y">
              {off.data.map((o) => (
                <li key={o.id} className="flex flex-wrap items-center gap-x-3 py-2 text-sm">
                  <bdi className="font-medium">{o.user_name}</bdi>
                  <span className="text-muted-foreground">{typeName(o, i18n.language)}</span>
                  <bdi dir="ltr" className="ms-auto font-latin text-muted-foreground">{dateRange(fmt, o.start_date, o.end_date)}</bdi>
                  {o.start_date <= today && today <= o.end_date && <Badge variant="secondary" className="font-normal">{t('leave.offToday')}</Badge>}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      {canApprove && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">{t('leave.teamBalances', { year })}</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            {balances.isLoading ? (
              <Skeleton className="h-24" />
            ) : (
              <table className="w-full min-w-[520px] text-sm">
                <thead>
                  <tr className="border-b text-xs text-muted-foreground">
                    <th className="py-2 text-start font-medium">{t('leave.person')}</th>
                    {limited.map((lt) => (
                      <th key={lt.id} className="py-2 text-center font-medium">{typeName(lt, i18n.language)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {people.map(([id, name]) => (
                    <tr key={id} className="border-b last:border-0">
                      <td className="py-2"><bdi>{name}</bdi></td>
                      {limited.map((lt) => {
                        const b = balances.data!.find((x) => x.user === id && x.leave_type === lt.id)!
                        return (
                          <td key={lt.id} className="py-2 text-center">
                            <span className="font-latin">{shortDays(b.remaining)}</span>
                            <span className="text-xs text-muted-foreground"> / <span className="font-latin">{shortDays(b.allowance)}</span></span>
                            {canManage && (
                              <Button variant="ghost" size="icon-xs" className="ms-1" onClick={() => setEditing(b)} aria-label={t('leave.editAllowance', { name, type: typeName(lt, i18n.language) })}>
                                <Pencil className="size-3" />
                              </Button>
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="mt-2 text-xs text-muted-foreground">{t('leave.balancesHint')}</p>
          </CardContent>
        </Card>
      )}
      {editing && <AllowanceDialog balance={editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

function AllowanceDialog({ balance, onClose }: { balance: LeaveBalance; onClose: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [allowance, setAllowance] = useState(shortDays(balance.allowance))
  const [note, setNote] = useState(balance.note)
  const save = useMutation({
    mutationFn: async () => api.patch('/leave/balances/', { user: balance.user, leave_type: balance.leave_type, year: balance.year, allowance, note }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LEAVE_KEY })
      toast.success(t('common.saved'))
      onClose()
    },
    onError: (e) => toast.error(Object.values(apiError(e).fields)[0] ?? apiError(e).message),
  })
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t('leave.allowanceFor', { name: balance.user_name, year: balance.year })}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>{t('common.save')}</Button>
        </>
      }
    >
      <div className="grid gap-4">
        <FormField id="al-days" label={t('leave.allowance')} hint={t('leave.allowanceHint')}>
          <Input id="al-days" type="number" min={0} max={365} step={0.5} value={allowance} onChange={(e) => setAllowance(e.target.value)} className="font-latin" />
        </FormField>
        <FormField id="al-note" label={t('leave.allowanceNote')}>
          <Input id="al-note" value={note} dir="auto" maxLength={200} onChange={(e) => setNote(e.target.value)} placeholder={t('leave.allowanceNotePlaceholder')} />
        </FormField>
      </div>
    </FormDialog>
  )
}

// ------------------------------------------------------------------ settings (admins)

function LeaveSettings() {
  const { t, i18n } = useTranslation()
  const { data: types, isLoading } = useLeaveTypes()
  const [editing, setEditing] = useState<LeaveType | 'new' | null>(null)
  return (
    <Card>
      <CardHeader className="flex flex-row items-center gap-2">
        <Settings2 className="size-4 text-muted-foreground" />
        <CardTitle className="flex-1 text-sm font-medium">{t('leave.types')}</CardTitle>
        <Button size="sm" onClick={() => setEditing('new')}>
          <Plus className="size-4" />
          {t('leave.newType')}
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-24" />
        ) : (
          <ul className="divide-y">
            {(types ?? []).map((lt) => (
              <li key={lt.id} className={cn('flex flex-wrap items-center gap-2 py-2.5 text-sm', !lt.is_active && 'opacity-60')}>
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{typeName(lt, i18n.language)}</span>
                  {i18n.language !== 'ur' && lt.name_ur && <span className="ms-2 text-muted-foreground">{lt.name_ur}</span>}
                </span>
                <span className="text-muted-foreground">{lt.days_per_year === null ? t('leave.noLimitShort') : t('leave.perYear', { days: shortDays(lt.days_per_year) })}</span>
                {!lt.paid && <Badge variant="outline" className="font-normal">{t('leave.unpaid')}</Badge>}
                {!lt.allow_half_days && <Badge variant="outline" className="font-normal">{t('leave.wholeDaysOnly')}</Badge>}
                {!lt.is_active && <Badge variant="outline" className="font-normal">{t('leave.inactive')}</Badge>}
                <Button variant="ghost" size="icon-sm" onClick={() => setEditing(lt)} aria-label={t('leave.editType', { name: lt.name })}>
                  <Pencil className="size-4" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
      {editing && <TypeDialog leaveType={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
    </Card>
  )
}

function TypeDialog({ leaveType, onClose }: { leaveType?: LeaveType; onClose: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    name: leaveType?.name ?? '',
    name_ur: leaveType?.name_ur ?? '',
    limited: leaveType ? leaveType.days_per_year !== null : true,
    days: leaveType?.days_per_year ? shortDays(leaveType.days_per_year) : '10',
    paid: leaveType?.paid ?? true,
    allow_half_days: leaveType?.allow_half_days ?? true,
    is_active: leaveType?.is_active ?? true,
  })
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }))
  const save = useMutation({
    mutationFn: async () => {
      const body = { name: form.name, name_ur: form.name_ur, days_per_year: form.limited ? form.days : null, paid: form.paid, allow_half_days: form.allow_half_days, is_active: form.is_active }
      return leaveType ? api.patch(`/leave/types/${leaveType.id}/`, body) : api.post('/leave/types/', body)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LEAVE_KEY })
      toast.success(t('common.saved'))
      onClose()
    },
    onError: (e) => toast.error(Object.values(apiError(e).fields)[0] ?? apiError(e).message),
  })
  const toggle = (k: 'limited' | 'paid' | 'allow_half_days' | 'is_active', label: string) => (
    <label className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm">
      {label}
      <Switch checked={form[k]} onCheckedChange={(v) => set(k, v)} />
    </label>
  )
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={leaveType ? t('leave.editType', { name: leaveType.name }) : t('leave.newType')}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !form.name.trim()}>{t('common.save')}</Button>
        </>
      }
    >
      <div className="grid gap-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField id="lt-name" label={t('leave.typeName')}>
            <Input id="lt-name" value={form.name} maxLength={80} onChange={(e) => set('name', e.target.value)} />
          </FormField>
          <FormField id="lt-name-ur" label={t('leave.typeNameUr')}>
            <Input id="lt-name-ur" value={form.name_ur} dir="rtl" maxLength={80} onChange={(e) => set('name_ur', e.target.value)} />
          </FormField>
        </div>
        {toggle('limited', t('leave.limited'))}
        {form.limited && (
          <FormField id="lt-days" label={t('leave.daysPerYear')}>
            <Input id="lt-days" type="number" min={0} max={365} step={0.5} value={form.days} onChange={(e) => set('days', e.target.value)} className="font-latin sm:w-40" />
          </FormField>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          {toggle('paid', t('leave.paid'))}
          {toggle('allow_half_days', t('leave.halfDaysAllowed'))}
          {toggle('is_active', t('leave.active'))}
        </div>
      </div>
    </FormDialog>
  )
}
