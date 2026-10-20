import { useTranslation } from 'react-i18next'
import { ErrorState } from '@/components/common'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useFormat } from '@/lib/format'
import { pct, useInteractionsReport, usePipelineReport, type FunnelRow, type InteractionBucket, type ReportFilters } from '@/lib/reports'
import { RateBar, Tile } from './bits'

function useBucketLabel(by: 'week' | 'month') {
  const fmt = useFormat()
  const { i18n } = useTranslation()
  return (b: InteractionBucket) =>
    by === 'month'
      ? new Intl.DateTimeFormat(i18n.language, { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${b.from}T12:00:00Z`))
      : `${fmt.date(`${b.from}T12:00:00`)} – ${fmt.date(`${b.to}T12:00:00`)}`
}

/** Interactions per week or month: one series (the total), columns from the baseline, the count on hover and in the table. */
function Columns({ buckets, label }: { buckets: InteractionBucket[]; label: (b: InteractionBucket) => string }) {
  const { t } = useTranslation()
  const max = Math.max(1, ...buckets.map((b) => b.total))
  return (
    <div className="overflow-x-auto" role="img" aria-label={t('reports.interactions.chartLabel')}>
      <div className="flex h-40 min-w-full items-end gap-[2px] border-b border-border" style={{ minWidth: `${buckets.length * 14}px` }}>
        {buckets.map((b) => (
          <div key={b.from} className="group relative flex h-full min-w-2.5 flex-1 items-end justify-center" title={`${label(b)}: ${b.total}`}>
            <div className="w-full max-w-10 rounded-t-[4px] bg-primary/80 transition-colors group-hover:bg-primary" style={{ height: `${(b.total / max) * 100}%`, minHeight: b.total ? 2 : 0 }} />
          </div>
        ))}
      </div>
    </div>
  )
}

export function Interactions({ filters }: { filters: ReportFilters }) {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useInteractionsReport(filters)
  const label = useBucketLabel(data?.by ?? 'week')
  if (isError) return <ErrorState onRetry={() => void refetch()} />
  if (isLoading || !data) return <Skeleton className="h-72 rounded-xl" />
  const busiest = data.buckets.reduce((a, b) => (b.total > a.total ? b : a), data.buckets[0])
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label={t('reports.interactions.total')} value={data.totals.total} />
        <Tile label={t('reports.interactions.clients')} value={data.totals.clients} />
        <Tile label={t(`reports.interactions.average_${data.by}`)} value={data.buckets.length ? Math.round((data.totals.total / data.buckets.length) * 10) / 10 : 0} />
        <Tile label={t(`reports.interactions.busiest_${data.by}`)} value={busiest?.total ?? 0} hint={busiest?.total ? label(busiest) : undefined} />
      </div>
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">{t(`reports.interactions.per_${data.by}`)}</CardTitle></CardHeader>
        <CardContent className="grid gap-4">
          <Columns buckets={data.buckets} label={label} />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="py-2 pe-3 text-start font-medium">{t(`reports.interactions.${data.by}`)}</th>
                  {data.kinds.map((k) => <th key={k} className="px-2 py-2 text-end font-medium">{t(`reports.interactions.kinds.${k}`)}</th>)}
                  <th className="ps-2 py-2 text-end font-medium">{t('reports.interactions.totalColumn')}</th>
                </tr>
              </thead>
              <tbody>
                {data.buckets.map((b) => (
                  <tr key={b.from} className="border-b last:border-0">
                    <td className="py-2 pe-3"><bdi dir="ltr" className="font-latin">{label(b)}</bdi></td>
                    {data.kinds.map((k) => <td key={k} className="px-2 py-2 text-end font-latin tabular-nums">{b.counts[k]}</td>)}
                    <td className="ps-2 py-2 text-end font-latin font-medium tabular-nums">{b.total}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">{t('reports.byPerson')}</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr className="border-b">
                <th className="py-2 pe-3 text-start font-medium">{t('reports.person')}</th>
                {data.kinds.map((k) => <th key={k} className="px-2 py-2 text-end font-medium">{t(`reports.interactions.kinds.${k}`)}</th>)}
                <th className="px-2 py-2 text-end font-medium">{t('reports.interactions.totalColumn')}</th>
                <th className="ps-2 py-2 text-end font-medium">{t('reports.interactions.clients')}</th>
              </tr>
            </thead>
            <tbody>
              {data.people.map((p) => (
                <tr key={p.id} className="border-b last:border-0">
                  <td className="py-2 pe-3 font-medium"><bdi>{p.name}</bdi></td>
                  {data.kinds.map((k) => <td key={k} className="px-2 py-2 text-end font-latin tabular-nums">{p.counts[k]}</td>)}
                  <td className="px-2 py-2 text-end font-latin font-medium tabular-nums">{p.total}</td>
                  <td className="ps-2 py-2 text-end font-latin tabular-nums">{p.clients}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">{t('reports.interactions.note')}</p>
    </div>
  )
}

const STAGES = ['created', 'contacted', 'in_discussion', 'won'] as const

export function Pipeline({ filters }: { filters: ReportFilters }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const { data, isLoading, isError, refetch } = usePipelineReport(filters)
  if (isError) return <ErrorState onRetry={() => void refetch()} />
  if (isLoading || !data) return <Skeleton className="h-72 rounded-xl" />
  const f = data.funnel
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label={t('reports.pipeline.created')} value={f.created} />
        <Tile label={t('reports.pipeline.winRate')} value={pct(f.win_rate)} hint={t('reports.pipeline.winRateHint', { won: f.won, closed: f.won + f.lost })} />
        <Tile label={t('reports.pipeline.conversion')} value={pct(f.conversion)} hint={t('reports.pipeline.conversionHint', { won: f.won, created: f.created })} />
        <Tile label={t('reports.pipeline.wonInPeriod')} value={data.won_in_period}
          hint={data.average_days_to_win === null ? undefined : t('reports.pipeline.daysToWin', { days: fmt.number(data.average_days_to_win) })} />
      </div>
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">{t('reports.pipeline.funnel')}</CardTitle></CardHeader>
        <CardContent className="grid gap-2">
          {STAGES.map((s) => (
            <div key={s} className="grid grid-cols-[9rem_1fr_3rem] items-center gap-3 text-sm">
              <span className="text-muted-foreground">{t(`reports.pipeline.stages.${s}`)}</span>
              <span className="h-2.5 overflow-hidden rounded-full bg-muted">
                <span className="block h-full rounded-full bg-primary" style={{ width: f.created ? `${(f[s] / f.created) * 100}%` : 0 }} />
              </span>
              <span className="text-end font-latin tabular-nums">{f[s]}</span>
            </div>
          ))}
          <p className="text-xs text-muted-foreground">{t('reports.pipeline.funnelNote', { lost: f.lost, open: f.open })}</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">{t('reports.byPerson')}</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto">
          <PipelineTable rows={data.people} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">{t('reports.pipeline.moves')}</CardTitle></CardHeader>
        <CardContent>
          {!data.moves.length ? <p className="text-sm text-muted-foreground">{t('reports.pipeline.noMoves')}</p> : (
            <ul className="grid gap-1.5 text-sm sm:grid-cols-2">
              {data.moves.map((m) => (
                <li key={`${m.from}-${m.to}`} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1">{t(`contacts.statuses.${m.from}`)} <span aria-hidden className="inline-block rtl:rotate-180">→</span> {t(`contacts.statuses.${m.to}`)}</span>
                  <span className="font-latin tabular-nums">{m.count}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      <p className="text-xs text-muted-foreground">{t('reports.pipeline.note')}</p>
    </div>
  )
}

function PipelineTable({ rows }: { rows: FunnelRow[] }) {
  const { t } = useTranslation()
  const cols = ['created', 'contacted', 'in_discussion', 'won', 'lost', 'open'] as const
  return (
    <table className="w-full min-w-[44rem] text-sm">
      <thead className="text-xs text-muted-foreground">
        <tr className="border-b">
          <th className="py-2 pe-3 text-start font-medium">{t('reports.person')}</th>
          {cols.map((c) => <th key={c} className="px-2 py-2 text-end font-medium">{t(`reports.pipeline.columns.${c}`)}</th>)}
          <th className="px-2 py-2 text-start font-medium">{t('reports.pipeline.winRate')}</th>
          <th className="ps-2 py-2 text-start font-medium">{t('reports.pipeline.conversion')}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.id}-${i}`} className="border-b last:border-0">
            <td className="py-2 pe-3 font-medium"><bdi>{r.name ?? t('reports.pipeline.unassigned')}</bdi></td>
            {cols.map((c) => <td key={c} className="px-2 py-2 text-end font-latin tabular-nums">{r[c]}</td>)}
            <td className="px-2 py-2"><RateBar value={r.win_rate} label={t('reports.pipeline.winRate')} /></td>
            <td className="ps-2 py-2"><RateBar value={r.conversion} label={t('reports.pipeline.conversion')} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
