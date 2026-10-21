import { useTranslation } from 'react-i18next'
import { ErrorState } from '@/components/common'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useFormat } from '@/lib/format'
import { typeName } from '@/lib/leave'
import { pct, useAttendanceReport, type AttendanceRow, type ReportFilters } from '@/lib/reports'
import { cn } from '@/lib/utils'
import { RateBar, Tile } from './bits'

const DAY_COLUMNS = ['working_days', 'office', 'field', 'remote', 'late', 'leave', 'absent'] as const

function DaysTable({ rows, first, label }: { rows: AttendanceRow[]; first: string; label: (r: AttendanceRow) => string }) {
  const { t } = useTranslation()
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[46rem] text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr className="border-b">
            <th className="py-2 pe-3 text-start font-medium">{first}</th>
            {DAY_COLUMNS.map((c) => <th key={c} className="px-2 py-2 text-end font-medium">{t(`reports.attendance.columns.${c}`)}</th>)}
            <th className="ps-2 py-2 text-start font-medium">{t('reports.attendance.rate')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b last:border-0">
              <td className="py-2 pe-3 font-medium"><bdi>{label(r)}</bdi></td>
              {DAY_COLUMNS.map((c) => (
                <td key={c} className={cn('px-2 py-2 text-end font-latin tabular-nums', c === 'absent' && r.absent > 0 && 'text-destructive')}>{r[c]}</td>
              ))}
              <td className="ps-2 py-2"><RateBar value={r.rate} label={t('reports.attendance.rate')} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const days = (n: number | null | undefined) => (n === null || n === undefined ? '—' : String(n))

/** Attendance over the period's working days, and leave taken and left, by person and department. */
export function Attendance({ filters }: { filters: ReportFilters }) {
  const { t, i18n } = useTranslation()
  const fmt = useFormat()
  const { data, isLoading, isError, refetch } = useAttendanceReport(filters)
  if (isError) return <ErrorState onRetry={() => void refetch()} />
  if (isLoading || !data) return <Skeleton className="h-72 rounded-xl" />
  const tt = data.totals
  const types = data.leave_types
  const limited = types.filter((x) => x.limited)
  const checkIns = tt.office + tt.field + tt.remote
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label={t('reports.attendance.rate')} value={pct(tt.rate)} hint={t('reports.attendance.rateHint', { n: tt.attended, due: tt.attended + tt.absent })} />
        <Tile label={t('reports.attendance.absent')} value={tt.absent} tone={tt.absent ? 'bad' : undefined}
          hint={t('reports.attendance.workingDaysHint', { n: data.period_working_days, holidays: data.holidays })} />
        <Tile label={t('reports.attendance.late')} value={tt.late} hint={t('reports.attendance.lateHint', { n: checkIns })} />
        <Tile label={t('reports.attendance.leaveTaken')} value={data.leave_totals.total} hint={t('reports.attendance.waitingHint', { n: data.leave_totals.waiting })} />
      </div>
      {data.departments.length > 1 && (
        <Card>
          <CardHeader><CardTitle className="text-sm font-medium">{t('reports.byDepartment')}</CardTitle></CardHeader>
          <CardContent><DaysTable rows={data.departments} first={t('reports.department')} label={(r) => r.name ?? t('reports.noDepartment')} /></CardContent>
        </Card>
      )}
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">{t('reports.byPerson')}</CardTitle></CardHeader>
        <CardContent><DaysTable rows={data.people} first={t('reports.person')} label={(r) => r.name ?? ''} /></CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">{t('reports.attendance.leaveTitle')}</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr className="border-b">
                <th className="py-2 pe-3 text-start font-medium">{t('reports.person')}</th>
                {types.map((x) => <th key={x.id} className="px-2 py-2 text-end font-medium"><bdi>{typeName(x, i18n.language)}</bdi></th>)}
                <th className="px-2 py-2 text-end font-medium">{t('reports.attendance.total')}</th>
                <th className="ps-2 py-2 text-end font-medium">{t('reports.attendance.waiting')}</th>
              </tr>
            </thead>
            <tbody>
              {data.leave.map((r) => (
                <tr key={r.id} className="border-b last:border-0">
                  <td className="py-2 pe-3 font-medium"><bdi>{r.name}</bdi></td>
                  {types.map((x) => (
                    <td key={x.id} className={cn('px-2 py-2 text-end font-latin tabular-nums', !r.taken[x.id] && 'text-muted-foreground')}>{days(r.taken[x.id])}</td>
                  ))}
                  <td className="px-2 py-2 text-end font-latin font-medium tabular-nums">{days(r.total)}</td>
                  <td className="ps-2 py-2 text-end font-latin tabular-nums">{days(r.waiting)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t font-medium">
                <td className="py-2 pe-3">{t('reports.attendance.all')}</td>
                {types.map((x) => <td key={x.id} className="px-2 py-2 text-end font-latin tabular-nums">{days(x.taken)}</td>)}
                <td className="px-2 py-2 text-end font-latin tabular-nums">{days(data.leave_totals.total)}</td>
                <td className="ps-2 py-2 text-end font-latin tabular-nums">{days(data.leave_totals.waiting)}</td>
              </tr>
            </tfoot>
          </table>
          <p className="mt-2 text-xs text-muted-foreground">{t('reports.attendance.leaveNote')}</p>
        </CardContent>
      </Card>
      {limited.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-sm font-medium">{t('reports.attendance.leftTitle', { year: data.year })}</CardTitle></CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full min-w-[28rem] text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="py-2 pe-3 text-start font-medium">{t('reports.person')}</th>
                  {limited.map((x) => <th key={x.id} className="ps-2 py-2 text-end font-medium"><bdi>{typeName(x, i18n.language)}</bdi></th>)}
                </tr>
              </thead>
              <tbody>
                {data.leave.map((r) => (
                  <tr key={r.id} className="border-b last:border-0">
                    <td className="py-2 pe-3 font-medium"><bdi>{r.name}</bdi></td>
                    {limited.map((x) => {
                      const left = r.remaining[x.id]
                      return <td key={x.id} className={cn('ps-2 py-2 text-end font-latin tabular-nums', left !== null && left <= 0 && 'text-destructive')}>{days(left)}</td>
                    })}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t font-medium">
                  <td className="py-2 pe-3">{t('reports.attendance.all')}</td>
                  {limited.map((x) => (
                    <td key={x.id} className="ps-2 py-2 text-end font-latin tabular-nums">
                      <bdi dir="ltr">{days(x.remaining)} / {days(x.allowance)}</bdi>
                    </td>
                  ))}
                </tr>
              </tfoot>
            </table>
            <p className="mt-2 text-xs text-muted-foreground">{t('reports.attendance.leftNote')}</p>
          </CardContent>
        </Card>
      )}
      <p className="text-xs text-muted-foreground">
        {t('reports.attendance.note', { date: fmt.date(`${data.as_of}T12:00:00`) })}
      </p>
    </div>
  )
}
