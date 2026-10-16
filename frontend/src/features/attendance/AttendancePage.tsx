import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Pencil } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ErrorState, FormDialog, FormField, PageHeader, SimpleSelect } from '@/components/common'
import { MonthNav } from '@/components/common/MonthNav'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api, apiError } from '@/lib/api'
import {
  ATTENDANCE_KEY,
  COUNTED,
  STATUS_STYLES,
  useAttendanceMonth,
  useTeamDay,
  useTeamMonth,
  type AttendanceDay,
  type AttendanceMode,
  type Counts,
  type TeamDayRow,
} from '@/lib/attendance'
import { addDays, officeParts, todayInOffice } from '@/lib/bookings'
import { useFormat } from '@/lib/format'
import { typeName } from '@/lib/leave'
import { usePermission } from '@/lib/permissions'
import { useDepartments } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { CheckInCard } from './CheckInCard'

type Tab = 'me' | 'team' | 'month'
const LETTER: Record<string, string> = { present: 'P', field: 'F', remote: 'R', leave: 'L', off: '', not_in: '·', absent: 'A', upcoming: '' }

/** Attendance: my month (with check-in), my team's day (with corrections), and the team's month grid. */
export function AttendancePage() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const [params, setParams] = useSearchParams()
  const canManage = usePermission('attendance.edit')
  const today = todayInOffice(fmt.settings.timezone)
  const asked = params.get('tab')
  const tab: Tab = canManage && (asked === 'team' || asked === 'month') ? asked : 'me'
  const month = params.get('month') ?? today.slice(0, 7)
  const set = (changes: Record<string, string | undefined>) =>
    setParams((p) => {
      for (const [k, v] of Object.entries(changes)) {
        if (v) p.set(k, v)
        else p.delete(k)
      }
      return p
    }, { replace: true })
  return (
    <>
      <PageHeader title={t('attendance.title')} subtitle={t('attendance.subtitle')} />
      {canManage && (
        <Tabs value={tab} onValueChange={(v) => set({ tab: v === 'me' ? undefined : String(v) })} className="mb-4">
          <TabsList>
            <TabsTrigger value="me">{t('attendance.tabs.me')}</TabsTrigger>
            <TabsTrigger value="team">{t('attendance.tabs.team')}</TabsTrigger>
            <TabsTrigger value="month">{t('attendance.tabs.month')}</TabsTrigger>
          </TabsList>
        </Tabs>
      )}
      {tab === 'me' ? (
        <div className="grid gap-4">
          <CheckInCard showTeam={false} />
          <MyMonth month={month} onMonth={(m) => set({ month: m })} />
        </div>
      ) : tab === 'team' ? (
        <TeamDay date={params.get('date') ?? today} onDate={(d) => set({ date: d })} />
      ) : (
        <TeamMonth month={month} onMonth={(m) => set({ month: m })} />
      )}
    </>
  )
}

function Totals({ counts }: { counts: Counts }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  return (
    <div className="flex flex-wrap gap-1.5">
      {COUNTED.map((k) => (
        <Badge key={k} variant="outline" className={cn('gap-1 font-normal', k === 'late' ? 'border-amber-500/50 text-amber-700 dark:text-amber-300' : STATUS_STYLES[k])}>
          <span className="font-latin">{fmt.number(counts[k])}</span>
          {t(k === 'late' ? 'attendance.late' : `attendance.status.${k}`)}
        </Badge>
      ))}
    </div>
  )
}

function StatusBadges({ day }: { day: AttendanceDay }) {
  const { t, i18n } = useTranslation()
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <Badge variant="outline" className={cn('font-normal', STATUS_STYLES[day.status])}>
        {day.status === 'leave' && day.leave ? typeName({ name: day.leave.type, name_ur: day.leave.type_ur }, i18n.language) : t(`attendance.status.${day.status}`)}
      </Badge>
      {day.late && <Badge variant="outline" className="border-amber-500/50 font-normal text-amber-700 dark:text-amber-300">{t('attendance.late')}</Badge>}
      {day.leave?.half_day && day.status !== 'leave' && <Badge variant="outline" className="font-normal">{t('attendance.halfDayLeave')}</Badge>}
      {day.corrected && <Badge variant="outline" className="font-normal text-muted-foreground">{t('attendance.corrected')}</Badge>}
    </span>
  )
}

function Times({ day }: { day: AttendanceDay }) {
  const fmt = useFormat()
  if (!day.check_in) return null
  return (
    <span className="text-sm">
      {fmt.time(day.check_in)}–{day.check_out ? fmt.time(day.check_out) : '…'}
    </span>
  )
}

function MyMonth({ month, onMonth }: { month: string; onMonth: (m: string) => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const { data, isLoading, isError, refetch } = useAttendanceMonth(month)
  const today = todayInOffice(fmt.settings.timezone)
  return (
    <Card className="gap-3">
      <CardContent className="grid gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <MonthNav month={month} onMonth={onMonth} />
          {data && <Totals counts={data.totals} />}
        </div>
        {isError ? (
          <ErrorState onRetry={() => void refetch()} />
        ) : isLoading || !data ? (
          <Skeleton className="h-64" />
        ) : (
          <ul className="divide-y">
            {data.days
              .filter((d) => d.date <= today)
              .reverse()
              .map((d) => (
                <li key={d.date} className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 py-2', d.status === 'off' && 'opacity-60')}>
                  <span className="w-32 text-sm font-latin">{fmt.date(`${d.date}T12:00:00`)}</span>
                  <StatusBadges day={d} />
                  <Times day={d} />
                  {d.holiday && <bdi className="text-sm text-muted-foreground">{d.holiday}</bdi>}
                  {d.note && <span className="text-xs text-muted-foreground [unicode-bidi:plaintext]">{d.note}</span>}
                </li>
              ))}
          </ul>
        )}
        <p className="text-xs text-muted-foreground">{t('attendance.lateHint', { minutes: fmt.settings.late_after_minutes })}</p>
      </CardContent>
    </Card>
  )
}

function TeamDay({ date, onDate }: { date: string; onDate: (d: string) => void }) {
  const { t } = useTranslation()
  const [department, setDepartment] = useState('')
  const isAdmin = usePermission('users.create')
  const { data: departments } = useDepartments()
  const { data, isLoading, isError, refetch } = useTeamDay(date, department || undefined)
  const [editing, setEditing] = useState<TeamDayRow | null>(null)
  return (
    <Card className="gap-3">
      <CardContent className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="icon" aria-label={t('attendance.previous')} onClick={() => onDate(addDays(date, -1))}>
            <ChevronLeft className="size-4 rtl:rotate-180" />
          </Button>
          <Input type="date" value={date} onChange={(e) => e.target.value && onDate(e.target.value)} aria-label={t('attendance.date')} className="w-40 font-latin" />
          <Button variant="outline" size="icon" aria-label={t('attendance.next')} onClick={() => onDate(addDays(date, 1))}>
            <ChevronRight className="size-4 rtl:rotate-180" />
          </Button>
          {isAdmin && (
            <div className="w-48">
              <SimpleSelect
                id="att-dept"
                value={department}
                onChange={setDepartment}
                options={[{ value: '', label: t('attendance.allDepartments') }, ...(departments ?? []).map((d) => ({ value: String(d.id), label: d.name }))]}
              />
            </div>
          )}
          {data && <div className="ms-auto"><Totals counts={data.counts} /></div>}
        </div>
        {isError ? (
          <ErrorState onRetry={() => void refetch()} />
        ) : isLoading || !data ? (
          <Skeleton className="h-64" />
        ) : (
          <ul className="divide-y">
            {data.rows.map((r) => (
              <li key={r.user} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
                <span className="min-w-40 flex-1">
                  <bdi className="block font-medium">{r.user_name}</bdi>
                  {r.department && <bdi className="block text-xs text-muted-foreground">{r.department}</bdi>}
                </span>
                <StatusBadges day={r} />
                <Times day={r} />
                {r.note && <span className="text-xs text-muted-foreground [unicode-bidi:plaintext]">{r.note}</span>}
                <Button variant="ghost" size="icon-sm" onClick={() => setEditing(r)} aria-label={t('attendance.correctFor', { name: r.user_name })} disabled={r.status === 'upcoming'}>
                  <Pencil className="size-4" />
                </Button>
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-muted-foreground">{t('attendance.correctHint')}</p>
      </CardContent>
      {editing && <CorrectionDialog row={editing} date={date} onClose={() => setEditing(null)} />}
    </Card>
  )
}

function CorrectionDialog({ row, date, onClose }: { row: TeamDayRow; date: string; onClose: () => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const tz = fmt.settings.timezone
  const queryClient = useQueryClient()
  const [checkIn, setCheckIn] = useState(row.check_in ? officeParts(tz, row.check_in).time : fmt.settings.office_opens.slice(0, 5))
  const [checkOut, setCheckOut] = useState(row.check_out ? officeParts(tz, row.check_out).time : '')
  const [mode, setMode] = useState<AttendanceMode>(row.mode ?? 'office')
  const [note, setNote] = useState(row.note)
  const [clear, setClear] = useState(false)
  const save = useMutation({
    mutationFn: async () =>
      api.post('/attendance/correct/', { user: row.user, date, check_in: checkIn, check_out: checkOut || null, mode, note, clear }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ATTENDANCE_KEY })
      toast.success(t('attendance.correctedToast'))
      onClose()
    },
    onError: (e) => toast.error(Object.values(apiError(e).fields)[0] ?? apiError(e).message),
  })
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t('attendance.correctTitle', { name: row.user_name, date: fmt.date(`${date}T12:00:00`) })}
      description={t('attendance.correctDescription')}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || (!clear && !checkIn)}>{t('common.save')}</Button>
        </>
      }
    >
      <div className="grid gap-4">
        {row.check_in && (
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={clear} onCheckedChange={(v) => setClear(!!v)} />
            {t('attendance.clear')}
          </label>
        )}
        {!clear && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <FormField id="cr-in" label={t('attendance.checkInTime')}>
                <Input id="cr-in" type="time" value={checkIn} onChange={(e) => setCheckIn(e.target.value)} className="font-latin" />
              </FormField>
              <FormField id="cr-out" label={t('attendance.checkOutTime')}>
                <Input id="cr-out" type="time" value={checkOut} onChange={(e) => setCheckOut(e.target.value)} className="font-latin" />
              </FormField>
            </div>
            <FormField id="cr-mode" label={t('attendance.where')}>
              <SimpleSelect id="cr-mode" value={mode} onChange={(v) => setMode(v as AttendanceMode)} options={(['office', 'field', 'remote'] as const).map((m) => ({ value: m, label: t(`attendance.modes.${m}`) }))} />
            </FormField>
            <FormField id="cr-note" label={t('attendance.note')}>
              <Input id="cr-note" value={note} dir="auto" maxLength={300} onChange={(e) => setNote(e.target.value)} />
            </FormField>
          </>
        )}
      </div>
    </FormDialog>
  )
}

function TeamMonth({ month, onMonth }: { month: string; onMonth: (m: string) => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const { data, isLoading, isError, refetch } = useTeamMonth(month)
  return (
    <Card className="gap-3">
      <CardContent className="grid gap-3">
        <MonthNav month={month} onMonth={onMonth} />
        {isError ? (
          <ErrorState onRetry={() => void refetch()} />
        ) : isLoading || !data ? (
          <Skeleton className="h-64" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-max min-w-full border-separate border-spacing-0 text-xs">
              <thead>
                <tr>
                  <th className="sticky start-0 z-10 bg-card py-1.5 pe-3 text-start font-medium">{t('attendance.person')}</th>
                  {data.days.map((d) => (
                    <th key={d} className="w-7 py-1.5 text-center font-latin font-normal text-muted-foreground">{Number(d.slice(8))}</th>
                  ))}
                  <th className="px-2 text-center font-medium">{t('attendance.status.present')}</th>
                  <th className="px-2 text-center font-medium">{t('attendance.late')}</th>
                  <th className="px-2 text-center font-medium">{t('attendance.status.leave')}</th>
                  <th className="px-2 text-center font-medium">{t('attendance.status.absent')}</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.user}>
                    <td className="sticky start-0 z-10 max-w-44 truncate bg-card py-1 pe-3"><bdi>{r.user_name}</bdi></td>
                    {r.cells.map((c, i) => (
                      <td key={data.days[i]} className="p-0.5">
                        <span
                          className={cn('flex size-6 items-center justify-center rounded border font-latin text-[10px] font-medium', STATUS_STYLES[c.status], c.late && 'ring-1 ring-amber-500')}
                          title={`${fmt.date(`${data.days[i]}T12:00:00`)}: ${t(`attendance.status.${c.status}`)}${c.late ? ` (${t('attendance.late')})` : ''}`}
                        >
                          {LETTER[c.status]}
                        </span>
                      </td>
                    ))}
                    <td className="px-2 text-center font-latin">{r.totals.present + r.totals.field + r.totals.remote}</td>
                    <td className="px-2 text-center font-latin">{r.totals.late}</td>
                    <td className="px-2 text-center font-latin">{r.totals.leave}</td>
                    <td className="px-2 text-center font-latin">{r.totals.absent}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-muted-foreground">{t('attendance.legend')}</p>
      </CardContent>
    </Card>
  )
}
