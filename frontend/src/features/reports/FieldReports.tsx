import { useTranslation } from 'react-i18next'
import { ErrorState } from '@/components/common'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { pct, useErrandsReport, useFieldVisitsReport, type ErrandRow, type ReportFilters, type VisitRow } from '@/lib/reports'
import { cn } from '@/lib/utils'
import { RateBar, Tile } from './bits'

const VISIT_COLUMNS = ['scheduled', 'done', 'cancelled', 'not_closed', 'upcoming', 'checked_in', 'reported'] as const

function VisitTable({ rows, first, label }: { rows: VisitRow[]; first: string; label: (r: VisitRow) => string }) {
  const { t } = useTranslation()
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[46rem] text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr className="border-b">
            <th className="py-2 pe-3 text-start font-medium">{first}</th>
            {VISIT_COLUMNS.map((c) => <th key={c} className="px-2 py-2 text-end font-medium">{t(`reports.field.columns.${c}`)}</th>)}
            <th className="ps-2 py-2 text-start font-medium">{t('reports.field.completion')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b last:border-0">
              <td className="py-2 pe-3 font-medium"><bdi>{label(r)}</bdi></td>
              {VISIT_COLUMNS.map((c) => (
                <td key={c} className={cn('px-2 py-2 text-end font-latin tabular-nums', c === 'not_closed' && r.not_closed > 0 && 'text-destructive')}>{r[c]}</td>
              ))}
              <td className="ps-2 py-2"><RateBar value={r.completion} label={t('reports.field.completion')} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Field visits scheduled in the period: done vs. planned, by person, purpose and report outcome. */
export function FieldVisits({ filters }: { filters: ReportFilters }) {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useFieldVisitsReport(filters)
  if (isError) return <ErrorState onRetry={() => void refetch()} />
  if (isLoading || !data) return <Skeleton className="h-72 rounded-xl" />
  const tt = data.totals
  const reports = data.outcomes.reduce((n, o) => n + o.count, 0)
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label={t('reports.field.scheduled')} value={tt.scheduled} hint={t('reports.field.upcomingHint', { n: tt.upcoming })} />
        <Tile label={t('reports.field.completion')} value={pct(tt.completion)} hint={t('reports.field.completionHint', { done: tt.done, due: tt.done + tt.cancelled + tt.not_closed })} />
        <Tile label={t('reports.field.checkInRate')} value={pct(tt.check_in_rate)} hint={t('reports.field.checkInHint', { n: tt.checked_in })} />
        <Tile label={t('reports.field.notClosed')} value={tt.not_closed} tone={tt.not_closed ? 'bad' : undefined} hint={t('reports.field.reportedHint', { n: tt.reported })} />
      </div>
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">{t('reports.byPerson')}</CardTitle></CardHeader>
        <CardContent><VisitTable rows={data.people} first={t('reports.person')} label={(r) => r.name ?? ''} /></CardContent>
      </Card>
      <div className="grid gap-4">
        <Card>
          <CardHeader><CardTitle className="text-sm font-medium">{t('reports.field.byPurpose')}</CardTitle></CardHeader>
          <CardContent><VisitTable rows={data.purposes} first={t('reports.field.purpose')} label={(r) => t(`visits.purposes.${r.purpose}`)} /></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm font-medium">{t('reports.field.outcomes')}</CardTitle></CardHeader>
          <CardContent className="grid gap-2">
            {!reports ? <p className="text-sm text-muted-foreground">{t('reports.field.noReports')}</p> : data.outcomes.map((o) => (
              <div key={o.outcome} className="grid grid-cols-[minmax(0,1fr)_2.5rem] items-center gap-x-3 gap-y-1 text-sm">
                <span>{t(`visits.report.outcomes.${o.outcome}`)}</span>
                <span className="text-end font-latin tabular-nums">{o.count}</span>
                <span className="col-span-2"><RateBar value={o.share} label={t(`visits.report.outcomes.${o.outcome}`)} /></span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      <p className="text-xs text-muted-foreground">{t('reports.field.note')}</p>
    </div>
  )
}

const ERRAND_COLUMNS = ['asked', 'done', 'failed', 'cancelled', 'open', 'overdue'] as const

function ErrandTable({ rows, first, label }: { rows: ErrandRow[]; first: string; label: (r: ErrandRow) => string }) {
  const { t } = useTranslation()
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[46rem] text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr className="border-b">
            <th className="py-2 pe-3 text-start font-medium">{first}</th>
            {ERRAND_COLUMNS.map((c) => <th key={c} className="px-2 py-2 text-end font-medium">{t(`reports.errands.columns.${c}`)}</th>)}
            <th className="px-2 py-2 text-start font-medium">{t('reports.errands.success')}</th>
            <th className="ps-2 py-2 text-start font-medium">{t('reports.errands.onTime')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b last:border-0">
              <td className="py-2 pe-3 font-medium"><bdi>{label(r)}</bdi></td>
              {ERRAND_COLUMNS.map((c) => (
                <td key={c} className={cn('px-2 py-2 text-end font-latin tabular-nums', c === 'overdue' && r.overdue > 0 && 'text-destructive')}>{r[c]}</td>
              ))}
              <td className="px-2 py-2"><RateBar value={r.success} label={t('reports.errands.success')} /></td>
              <td className="ps-2 py-2"><RateBar value={r.on_time_rate} label={t('reports.errands.onTime')} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Errands due in the period: done and not done, by runner and kind. */
export function Errands({ filters }: { filters: ReportFilters }) {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useErrandsReport(filters)
  if (isError) return <ErrorState onRetry={() => void refetch()} />
  if (isLoading || !data) return <Skeleton className="h-72 rounded-xl" />
  const tt = data.totals
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label={t('reports.errands.asked')} value={tt.asked} hint={t('reports.errands.openHint', { n: tt.open })} />
        <Tile label={t('reports.errands.success')} value={pct(tt.success)} hint={t('reports.errands.successHint', { done: tt.done, failed: tt.failed })} />
        <Tile label={t('reports.errands.onTime')} value={pct(tt.on_time_rate)} hint={t('reports.errands.onTimeHint', { n: tt.on_time })} />
        <Tile label={t('reports.errands.overdue')} value={tt.overdue} tone={tt.overdue ? 'bad' : undefined} />
      </div>
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">{t('reports.byPerson')}</CardTitle></CardHeader>
        <CardContent><ErrandTable rows={data.people} first={t('reports.person')} label={(r) => r.name ?? t('reports.errands.nobodyYet')} /></CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">{t('reports.errands.byKind')}</CardTitle></CardHeader>
        <CardContent><ErrandTable rows={data.kinds} first={t('reports.errands.kind')} label={(r) => t(`errands.kinds.${r.kind}`)} /></CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">{t('reports.errands.note')}</p>
    </div>
  )
}
