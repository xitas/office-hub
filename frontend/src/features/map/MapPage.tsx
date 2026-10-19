import { ExternalLink, MapPin, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { ErrorState, PageHeader, SimpleSelect } from '@/components/common'
import { MapView } from '@/components/map'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CheckList } from '@/features/visits/CheckDialog'
import { addDays, todayInOffice, weekStartOf } from '@/lib/bookings'
import { useFormat } from '@/lib/format'
import { toNumber, useMapData, type MapData, type MapMarker, type MapRecord, type MapVisit } from '@/lib/map'
import { cn } from '@/lib/utils'
import { useVisitPeople, VISIT_TONE } from '@/lib/visits'

type Range = 'today' | 'week'
type LayerKey = 'visits' | 'checks' | 'contacts' | 'companies' | 'vendors'
const LAYERS: LayerKey[] = ['visits', 'checks', 'contacts', 'companies', 'vendors']
const STATUSES = ['all', 'planned', 'done', 'pending'] as const
const RECORD_KIND = { contacts: 'contact', companies: 'company', vendors: 'vendor' } as const
const RECORD_PATH = { contacts: '/contacts', companies: '/companies', vendors: '/vendors' } as const

/**
 * Field visits on a map, for managers and admins: today's or this week's, by person and status, at the visit's pin
 * (or its client's or vendor's); where people checked in and out (only those the viewer may see, and gone after
 * 90 days); and the pins of contacts, companies and vendors. On phones the list is a tab next to the map.
 */
export function MapPage() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const [params, setParams] = useSearchParams()
  const { data: people } = useVisitPeople()
  const today = todayInOffice(fmt.settings.timezone)
  const range: Range = params.get('range') === 'week' ? 'week' : 'today'
  const person = params.get('person') ?? ''
  const status = params.get('status') ?? 'all'
  const from = range === 'week' ? weekStartOf(today, fmt.settings.week_start) : today
  const to = range === 'week' ? addDays(from, 6) : today
  const { data, isLoading, isError, refetch } = useMapData({ from, to, ...(person ? { person } : {}), status })
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({ visits: true, checks: true, contacts: false, companies: true, vendors: false })
  const [selected, setSelected] = useState<string | null>(null)
  const [view, setView] = useState<'map' | 'list'>('map')
  const set = (key: string, value: string) =>
    setParams((p) => {
      if (value) p.set(key, value)
      else p.delete(key)
      return p
    }, { replace: true })
  const markers = useMemo(() => (data ? buildMarkers(data, layers, t, fmt.time) : []), [data, layers, t, fmt.time])
  const pick = (id: string) => {
    setSelected(id)
    setView('list')
  }
  return (
    <>
      <PageHeader title={t('map.title')} subtitle={t('map.subtitle')} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Tabs value={range} onValueChange={(v) => set('range', v === 'week' ? 'week' : '')}>
          <TabsList>
            <TabsTrigger value="today">{t('map.today')}</TabsTrigger>
            <TabsTrigger value="week">{t('map.thisWeek')}</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="w-44">
          <SimpleSelect id="map-person" value={person} onChange={(v) => set('person', v)}
            options={[{ value: '', label: t('visits.everyone') }, ...(people?.plan_for ?? []).map((p) => ({ value: String(p.id), label: p.name }))]} />
        </div>
        <div className="w-40">
          <SimpleSelect id="map-status" value={status} onChange={(v) => set('status', v === 'all' ? '' : v)}
            options={STATUSES.map((s) => ({ value: s, label: s === 'all' ? t('map.allStatuses') : t(`visits.status.${s}`) }))} />
        </div>
      </div>
      <div className="mb-3 flex flex-wrap gap-1.5" role="group" aria-label={t('map.layers')}>
        {LAYERS.map((key) => (
          <button key={key} type="button" aria-pressed={layers[key]} onClick={() => setLayers((l) => ({ ...l, [key]: !l[key] }))}
            className={cn('inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-sm transition-colors',
              layers[key] ? 'border-primary bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted hover:text-foreground')}>
            <span className={cn('size-2.5 rounded-full', LEGEND[key])} aria-hidden />
            {t(`map.layer.${key}`)}
          </button>
        ))}
      </div>
      <Tabs value={view} onValueChange={(v) => setView(v === 'list' ? 'list' : 'map')} className="mb-3 lg:hidden">
        <TabsList>
          <TabsTrigger value="map">{t('map.mapTab')}</TabsTrigger>
          <TabsTrigger value="list">{t('map.listTab')}</TabsTrigger>
        </TabsList>
      </Tabs>
      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div className={cn('grid gap-2', view === 'list' && 'max-lg:hidden')}>
            {isLoading || !data ? (
              <Skeleton className="h-[60dvh] w-full rounded-xl" />
            ) : (
              <MapView label={t('map.title')} className="h-[60dvh] w-full overflow-hidden rounded-xl border lg:h-[calc(100dvh-17rem)] lg:min-h-96"
                markers={markers} selected={selected} onMarkerClick={pick} fit />
            )}
            <p className="text-xs text-muted-foreground">{t('map.privacyNote')}</p>
          </div>
          <div className={cn('grid content-start gap-3', view === 'map' && 'max-lg:hidden')}>
            {data && <Selected data={data} id={selected} onClose={() => setSelected(null)} />}
            {data && <VisitList visits={data.visits} selected={selected} onPick={setSelected} />}
          </div>
        </div>
      )}
    </>
  )
}

const LEGEND: Record<LayerKey, string> = {
  visits: 'bg-teal-600',
  checks: 'bg-emerald-600',
  contacts: 'bg-blue-500',
  companies: 'bg-purple-600',
  vendors: 'bg-orange-600',
}

function buildMarkers(data: MapData, layers: Record<LayerKey, boolean>, t: (k: string, o?: Record<string, unknown>) => string, time: (v: string) => string) {
  const out: MapMarker[] = []
  for (const v of data.visits) {
    const lat = toNumber(v.latitude)
    if (layers.visits && lat !== null) {
      out.push({ id: `visit:${v.id}`, kind: 'visit', lat, lng: toNumber(v.longitude)!, tone: v.status, label: `${v.title} · ${v.assigned_to_name} · ${time(v.start)}` })
    }
    if (!layers.checks) continue
    for (const c of v.checks) {
      if (c.in) out.push({ id: `visit:${v.id}`, kind: 'checkin', lat: Number(c.in.latitude), lng: Number(c.in.longitude), label: t('map.checkedIn', { name: c.user_name, time: time(c.checked_in_at) }) })
      if (c.out && c.checked_out_at) out.push({ id: `visit:${v.id}`, kind: 'checkout', lat: Number(c.out.latitude), lng: Number(c.out.longitude), label: t('map.checkedOut', { name: c.user_name, time: time(c.checked_out_at) }) })
    }
  }
  for (const key of ['contacts', 'companies', 'vendors'] as const) {
    if (!layers[key]) continue
    for (const r of data[key]) out.push({ id: `${key}:${r.id}`, kind: RECORD_KIND[key], lat: Number(r.latitude), lng: Number(r.longitude), label: r.name })
  }
  return out
}

function Selected({ data, id, onClose }: { data: MapData; id: string | null; onClose: () => void }) {
  const { t } = useTranslation()
  if (!id) return null
  const [kind, raw] = id.split(':')
  const close = (
    <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label={t('common.close')} className="shrink-0"><X className="size-4" /></Button>
  )
  if (kind === 'visit') {
    const v = data.visits.find((x) => x.id === Number(raw))
    return v ? <VisitCard visit={v} action={close} highlighted /> : null
  }
  const key = kind as keyof typeof RECORD_PATH
  const r: MapRecord | undefined = data[key]?.find((x) => x.id === Number(raw))
  if (!r) return null
  return (
    <Card className="gap-2 border-primary/50 py-3">
      <CardContent className="grid gap-1 px-4 text-sm">
        <div className="flex items-start gap-2">
          <bdi className="min-w-0 flex-1 font-medium">{r.name}</bdi>
          {close}
        </div>
        <span className="text-muted-foreground">{t(`map.kind.${RECORD_KIND[key]}`)}{r.city && <> · <bdi>{r.city}</bdi></>}</span>
        <Link to={`${RECORD_PATH[key]}/${r.id}`} className="inline-flex w-fit items-center gap-1 text-primary hover:underline">
          <ExternalLink className="size-3.5" />{t('map.open')}
        </Link>
      </CardContent>
    </Card>
  )
}

function VisitCard({ visit: v, action, highlighted, onPick }: { visit: MapVisit; action?: React.ReactNode; highlighted?: boolean; onPick?: () => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  return (
    <Card className={cn('gap-2 py-3', highlighted && 'border-primary/50')}>
      <CardContent className="grid gap-1.5 px-4 text-sm">
        <div className="flex items-start gap-2">
          {onPick ? (
            <button type="button" onClick={onPick} className="min-w-0 flex-1 text-start font-medium hover:underline [unicode-bidi:plaintext]">{v.title}</button>
          ) : (
            <span className="min-w-0 flex-1 font-medium [unicode-bidi:plaintext]">{v.title}</span>
          )}
          <Badge variant="outline" className={cn('font-normal', VISIT_TONE[v.status])}>{t(`visits.status.${v.status}`)}</Badge>
          {action}
        </div>
        <span className="text-muted-foreground">
          {fmt.date(v.start)} · {fmt.time(v.start)}–{fmt.time(v.end)} · <bdi>{v.assigned_to_name}</bdi>
        </span>
        <span className="flex items-center gap-1 text-muted-foreground">
          <MapPin className="size-3.5 shrink-0" />
          <bdi className="min-w-0 truncate">{v.place}</bdi>
          {v.pin_source === null && <Badge variant="outline" className="ms-1 font-normal">{t('map.noPin')}</Badge>}
          {v.pin_source === 'record' && <span className="text-xs">({t('map.atRecord')})</span>}
        </span>
        {highlighted && v.checks.length > 0 && <CheckList checks={v.checks} />}
        {highlighted && (
          <Link to={`/visits?visit=${v.id}`} className="inline-flex w-fit items-center gap-1 text-primary hover:underline">
            <ExternalLink className="size-3.5" />{t('map.openVisit')}
          </Link>
        )}
      </CardContent>
    </Card>
  )
}

function VisitList({ visits, selected, onPick }: { visits: MapVisit[]; selected: string | null; onPick: (id: string) => void }) {
  const { t } = useTranslation()
  if (!visits.length) return <p className="rounded-xl border p-4 text-sm text-muted-foreground">{t('map.noVisits')}</p>
  return (
    <ul className="grid gap-2" aria-label={t('map.visitList')}>
      {visits.filter((v) => `visit:${v.id}` !== selected).map((v) => (
        <li key={v.id}><VisitCard visit={v} onPick={() => onPick(`visit:${v.id}`)} /></li>
      ))}
    </ul>
  )
}
