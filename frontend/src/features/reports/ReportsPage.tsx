import { FileSpreadsheet, FileText, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ErrorState, FormField, PageHeader, SimpleSelect } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { todayInOffice } from '@/lib/bookings'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { useDepartments } from '@/lib/queries'
import {
  PERIOD_PRESETS, PERIOD_REPORTS, REPORTS, exportParams, pct, presetRange, useCompletionReport, useOverdueReport, useReportPeople,
  type CompletionRow, type PeriodPreset, type ReportFilters, type ReportKey,
} from '@/lib/reports'
import { downloadFile } from '@/lib/transfer'
import { cn } from '@/lib/utils'
import { Attendance } from './AttendanceReport'
import { RateBar, Tile } from './bits'
import { Interactions, Pipeline } from './ClientReports'
import { Errands, FieldVisits } from './FieldReports'

/**
 * Reports for managers (their department) and admins (everyone, or one department): task completion for a period
 * and overdue tasks as of today, with PDF and Excel exports. The numbers come from the API, which only counts what
 * the viewer may see.
 */
export function ReportsPage() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const [params, setParams] = useSearchParams()
  const isAdmin = usePermission('departments.create')
  const canExport = usePermission('reports.export')
  const { data: departments } = useDepartments()
  const report: ReportKey = REPORTS.includes(params.get('report') as ReportKey) ? (params.get('report') as ReportKey) : 'task-completion'
  const withPeriod = PERIOD_REPORTS.includes(report)
  const by = params.get('by') === 'month' ? 'month' : 'week'
  const preset = (PERIOD_PRESETS.includes(params.get('period') as PeriodPreset) ? params.get('period') : 'this_month') as PeriodPreset
  const today = todayInOffice(fmt.settings.timezone)
  const range = preset === 'custom'
    ? { from: params.get('from') ?? today, to: params.get('to') ?? today }
    : presetRange(preset, today, fmt.settings.week_start)
  const department = isAdmin ? params.get('department') ?? '' : ''
  const person = params.get('person') ?? ''
  const { data: people } = useReportPeople(department || undefined)
  const set = (changes: Record<string, string | undefined>) =>
    setParams((p) => {
      for (const [k, v] of Object.entries(changes)) {
        if (v) p.set(k, v)
        else p.delete(k)
      }
      return p
    }, { replace: true })
  const filters: ReportFilters = { department, person, ...(withPeriod ? range : {}), ...(report === 'client-interactions' ? { by } : {}) }
  const [exporting, setExporting] = useState<'pdf' | 'xlsx' | null>(null)
  const download = async (file: 'pdf' | 'xlsx') => {
    setExporting(file)
    try {
      await downloadFile(`/reports/${report}/export/`, exportParams(filters, file), `${report}.${file}`)
    } catch {
      toast.error(t('transfer.exportFailed'))
    } finally {
      setExporting(null)
    }
  }
  return (
    <>
      <PageHeader
        title={t('reports.title')}
        subtitle={t('reports.subtitle')}
        actions={canExport && (
          <>
            <Button variant="outline" disabled={!!exporting} onClick={() => void download('pdf')}>
              {exporting === 'pdf' ? <Loader2 className="size-4 animate-spin" /> : <FileText className="size-4" />}{t('reports.exportPdf')}
            </Button>
            <Button variant="outline" disabled={!!exporting} onClick={() => void download('xlsx')}>
              {exporting === 'xlsx' ? <Loader2 className="size-4 animate-spin" /> : <FileSpreadsheet className="size-4" />}{t('reports.exportExcel')}
            </Button>
          </>
        )}
      />
      <Tabs value={report} onValueChange={(v) => set({ report: v === 'task-completion' ? undefined : String(v) })} className="mb-4 max-w-full overflow-x-auto">
        <TabsList>
          {REPORTS.map((r) => <TabsTrigger key={r} value={r}>{t(`reports.names.${r}`)}</TabsTrigger>)}
        </TabsList>
      </Tabs>
      <Card className="mb-4">
        <CardContent className="flex flex-wrap items-end gap-3">
          {withPeriod && (
            <>
              <FormField id="rp-period" label={t('reports.period')} className="w-44">
                <SimpleSelect id="rp-period" value={preset} onChange={(v) => set({ period: v === 'this_month' ? undefined : v, ...(v === 'custom' ? range : { from: undefined, to: undefined }) })}
                  options={PERIOD_PRESETS.map((p) => ({ value: p, label: t(`reports.periods.${p}`) }))} />
              </FormField>
              {preset === 'custom' ? (
                <>
                  <FormField id="rp-from" label={t('reports.from')} className="w-40">
                    <Input id="rp-from" type="date" value={range.from} max={range.to} onChange={(e) => e.target.value && set({ from: e.target.value })} className="font-latin" />
                  </FormField>
                  <FormField id="rp-to" label={t('reports.to')} className="w-40">
                    <Input id="rp-to" type="date" value={range.to} min={range.from} onChange={(e) => e.target.value && set({ to: e.target.value })} className="font-latin" />
                  </FormField>
                </>
              ) : (
                <p className="pb-2 text-sm text-muted-foreground">
                  <bdi dir="ltr" className="font-latin">{fmt.date(`${range.from}T12:00:00`)} – {fmt.date(`${range.to}T12:00:00`)}</bdi>
                </p>
              )}
            </>
          )}
          {report === 'client-interactions' && (
            <FormField id="rp-by" label={t('reports.interactions.groupBy')} className="w-36">
              <SimpleSelect id="rp-by" value={by} onChange={(v) => set({ by: v === 'week' ? undefined : v })}
                options={[{ value: 'week', label: t('reports.interactions.byWeek') }, { value: 'month', label: t('reports.interactions.byMonth') }]} />
            </FormField>
          )}
          {isAdmin && (
            <FormField id="rp-dept" label={t('reports.department')} className="w-48">
              <SimpleSelect id="rp-dept" value={department} onChange={(v) => set({ department: v, person: undefined })}
                options={[{ value: '', label: t('reports.allDepartments') }, ...(departments ?? []).map((d) => ({ value: String(d.id), label: d.name }))]} />
            </FormField>
          )}
          <FormField id="rp-person" label={t('reports.person')} className="w-48">
            <SimpleSelect id="rp-person" value={person} onChange={(v) => set({ person: v })}
              options={[{ value: '', label: t('reports.everyone') }, ...(people?.people ?? []).map((p) => ({ value: String(p.id), label: p.name }))]} />
          </FormField>
        </CardContent>
      </Card>
      {report === 'task-completion' && <Completion filters={filters} />}
      {report === 'overdue-tasks' && <Overdue filters={filters} />}
      {report === 'client-interactions' && <Interactions filters={filters} />}
      {report === 'lead-pipeline' && <Pipeline filters={filters} />}
      {report === 'field-visits' && <FieldVisits filters={filters} />}
      {report === 'errands' && <Errands filters={filters} />}
      {report === 'attendance' && <Attendance filters={filters} />}
    </>
  )
}

const COLUMNS = ['due', 'done', 'on_time', 'late', 'overdue', 'open', 'completed'] as const

function CompletionTable({ rows, first, showDepartment }: { rows: CompletionRow[]; first: string; showDepartment?: boolean }) {
  const { t } = useTranslation()
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[46rem] text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr className="border-b">
            <th className="py-2 pe-3 text-start font-medium">{first}</th>
            {showDepartment && <th className="py-2 pe-3 text-start font-medium">{t('reports.department')}</th>}
            {COLUMNS.map((c) => <th key={c} className="px-2 py-2 text-end font-medium">{t(`reports.columns.${c}`)}</th>)}
            <th className="px-2 py-2 text-start font-medium">{t('reports.columns.rate')}</th>
            <th className="ps-2 py-2 text-start font-medium">{t('reports.columns.on_time_rate')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.id}-${i}`} className="border-b last:border-0">
              <td className="py-2 pe-3 font-medium"><bdi>{r.name ?? t('reports.noDepartment')}</bdi></td>
              {showDepartment && <td className="py-2 pe-3 text-muted-foreground"><bdi>{r.department ?? ''}</bdi></td>}
              {COLUMNS.map((c) => (
                <td key={c} className={cn('px-2 py-2 text-end font-latin tabular-nums', c === 'overdue' && r.overdue > 0 && 'text-destructive')}>{r[c]}</td>
              ))}
              <td className="px-2 py-2"><RateBar value={r.rate} label={t('reports.columns.rate')} /></td>
              <td className="ps-2 py-2"><RateBar value={r.on_time_rate} label={t('reports.columns.on_time_rate')} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Completion({ filters }: { filters: ReportFilters }) {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useCompletionReport(filters)
  if (isError) return <ErrorState onRetry={() => void refetch()} />
  if (isLoading || !data) return <Skeleton className="h-72 rounded-xl" />
  const tt = data.totals
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label={t('reports.tiles.due')} value={tt.due} />
        <Tile label={t('reports.tiles.rate')} value={pct(tt.rate)} hint={t('reports.tiles.rateHint', { done: tt.done, due: tt.due })} />
        <Tile label={t('reports.tiles.onTime')} value={pct(tt.on_time_rate)} hint={t('reports.tiles.onTimeHint', { n: tt.on_time })} />
        <Tile label={t('reports.tiles.overdue')} value={tt.overdue} tone={tt.overdue ? 'bad' : undefined} hint={t('reports.tiles.completedHint', { n: tt.completed })} />
      </div>
      {data.departments.length > 1 && (
        <Card>
          <CardHeader><CardTitle className="text-sm font-medium">{t('reports.byDepartment')}</CardTitle></CardHeader>
          <CardContent><CompletionTable rows={data.departments} first={t('reports.department')} /></CardContent>
        </Card>
      )}
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">{t('reports.byPerson')}</CardTitle></CardHeader>
        <CardContent><CompletionTable rows={data.people} first={t('reports.person')} showDepartment={data.departments.length > 1} /></CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">{t('reports.completionNote')}</p>
    </div>
  )
}

function Overdue({ filters }: { filters: ReportFilters }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const { data, isLoading, isError, refetch } = useOverdueReport(filters, true)
  if (isError) return <ErrorState onRetry={() => void refetch()} />
  if (isLoading || !data) return <Skeleton className="h-72 rounded-xl" />
  const rows = data.people.filter((p) => p.overdue > 0)
  const sum = (k: 'days_1_7' | 'days_8_30' | 'days_31_plus' | 'urgent') => data.people.reduce((n, p) => n + p[k], 0)
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label={t('reports.tiles.overdueNow')} value={data.total} tone={data.total ? 'bad' : undefined} hint={t('reports.asOf', { date: fmt.date(`${data.as_of}T12:00:00`) })} />
        <Tile label={t('reports.columns.days_1_7')} value={sum('days_1_7')} />
        <Tile label={t('reports.columns.days_8_30')} value={sum('days_8_30')} />
        <Tile label={t('reports.columns.days_31_plus')} value={sum('days_31_plus')} hint={t('reports.urgentHint', { n: sum('urgent') })} />
      </div>
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">{t('reports.byPerson')}</CardTitle></CardHeader>
        <CardContent>
          {!rows.length ? <p className="text-sm text-muted-foreground">{t('reports.noneOverdue')}</p> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[40rem] text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="py-2 pe-3 text-start font-medium">{t('reports.person')}</th>
                    <th className="py-2 pe-3 text-start font-medium">{t('reports.department')}</th>
                    {(['overdue', 'days_1_7', 'days_8_30', 'days_31_plus', 'urgent'] as const).map((c) => (
                      <th key={c} className="px-2 py-2 text-end font-medium">{t(`reports.columns.${c}`)}</th>
                    ))}
                    <th className="ps-2 py-2 text-start font-medium">{t('reports.columns.oldest')}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((p) => (
                    <tr key={p.id} className="border-b last:border-0">
                      <td className="py-2 pe-3 font-medium"><bdi>{p.name}</bdi></td>
                      <td className="py-2 pe-3 text-muted-foreground"><bdi>{p.department ?? ''}</bdi></td>
                      {(['overdue', 'days_1_7', 'days_8_30', 'days_31_plus', 'urgent'] as const).map((c) => (
                        <td key={c} className="px-2 py-2 text-end font-latin tabular-nums">{p[c]}</td>
                      ))}
                      <td className="ps-2 py-2 font-latin">{p.oldest ? fmt.date(`${p.oldest}T12:00:00`) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex flex-row items-center gap-2">
          <CardTitle className="flex-1 text-sm font-medium">{t('reports.overdueTasks')}</CardTitle>
          {data.total > data.tasks.length && <span className="text-xs text-muted-foreground">{t('reports.mostOverdue', { shown: data.tasks.length, total: data.total })}</span>}
        </CardHeader>
        <CardContent>
          {!data.tasks.length ? <p className="text-sm text-muted-foreground">{t('reports.noneOverdue')}</p> : (
            <ul className="grid gap-2">
              {data.tasks.map((task) => (
                <li key={task.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b pb-2 text-sm last:border-0">
                  <Link to={`/tasks/${task.id}`} className="min-w-0 flex-1 basis-56 font-medium text-primary hover:underline [unicode-bidi:plaintext]">{task.title}</Link>
                  <Badge variant="outline" className="font-normal text-destructive">{t('reports.daysLate', { count: task.days_late })}</Badge>
                  <span className="text-xs text-muted-foreground">{t(`tasks.priorities.${task.priority}`)}</span>
                  <span className="basis-full text-xs text-muted-foreground sm:basis-auto">
                    <bdi>{task.assignees.join(', ')}</bdi>{task.record && <> · <bdi>{task.record}</bdi></>}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
