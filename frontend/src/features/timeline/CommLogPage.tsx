import { useQuery } from '@tanstack/react-query'
import { Building2, Download, History, Loader2, Plus, Search, UserRound, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, FormDialog, FormField, PageHeader, Pagination, SimpleSelect } from '@/components/common'
import { RecordPicker, type Picked } from '@/components/common/RecordPicker'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { useUserOptions } from '@/lib/queries'
import { ENTRY_KINDS, KIND_ICONS, KIND_STYLES, type LogFilters, type TimelineItem } from '@/lib/timeline'
import { downloadFile } from '@/lib/transfer'
import type { Paginated } from '@/lib/types'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { cn } from '@/lib/utils'
import { EntryTitle, FollowUpStatus } from './EntryBits'
import { QuickNoteDialog } from './QuickNoteDialog'

const FILTER_KEYS = ['type', 'direction', 'logged_by', 'contact', 'company', 'date_from', 'date_to', 'follow_up', 'q'] as const
const PAGE_SIZE = 25

/** Every logged call, meeting, email, WhatsApp message and note on the contacts and companies you can see. */
export function CommLogPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const canExport = usePermission('contacts.export')
  const [logging, setLogging] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [search, setSearch] = useState(params.get('q') ?? '')
  const q = useDebouncedValue(search.trim(), 300)
  const page = Number(params.get('page') ?? 1)
  const filters: LogFilters = Object.fromEntries(
    FILTER_KEYS.map((k) => [k, k === 'q' ? q : params.get(k) ?? '']).filter(([, v]) => v),
  )
  const setMany = (values: Record<string, string>) =>
    setParams((p) => {
      for (const [key, value] of Object.entries(values)) {
        if (value) p.set(key, value)
        else p.delete(key)
      }
      p.delete('page')
      return p
    }, { replace: true })
  const set = (key: string, value: string) => setMany({ [key]: value })

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['timeline', 'log', filters, page],
    queryFn: async () => (await api.get<Paginated<TimelineItem>>('/timeline/log/', { params: { ...filters, page } })).data,
    placeholderData: (previous) => previous,
  })

  const exportCsv = async () => {
    setExporting(true)
    try {
      await downloadFile('/timeline/log/export/', filters as Record<string, unknown>, 'communication-log.csv')
    } catch {
      toast.error(t('transfer.exportFailed'))
    } finally {
      setExporting(false)
    }
  }
  const filtered = FILTER_KEYS.some((k) => k !== 'q' && params.get(k)) || !!q

  return (
    <>
      <PageHeader
        title={t('log.title')}
        subtitle={t('log.subtitle')}
        actions={
          <>
            {canExport && (
              <Button variant="outline" onClick={() => void exportCsv()} disabled={exporting} title={t('log.exportHint')}>
                {exporting ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
                {t('transfer.export')}
              </Button>
            )}
            <Button onClick={() => setLogging(true)}>
              <Plus className="size-4" />
              {t('log.add')}
            </Button>
          </>
        }
      />

      <Filters params={params} set={set} setMany={setMany} search={search} setSearch={setSearch} />

      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading ? (
        <div className="grid gap-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      ) : !data?.results.length ? (
        <EmptyState
          icon={History}
          title={filtered ? t('log.noMatches') : t('log.empty')}
          hint={filtered ? t('log.noMatchesHint') : t('log.emptyHint')}
          className="py-16"
        />
      ) : (
        <>
          <p className="mb-2 text-sm text-muted-foreground" aria-live="polite">
            {t('log.count', { count: data.count })}
          </p>
          <Card className="py-0">
            <CardContent className="px-0">
              <ol className="divide-y">
                {data.results.map((item) => (
                  <LogRow key={item.id} item={item} />
                ))}
              </ol>
            </CardContent>
          </Card>
          <Pagination page={page} count={data.count} pageSize={PAGE_SIZE} onPage={(n) => setParams((p) => (p.set('page', String(n)), p))} />
        </>
      )}

      {logging && (
        <QuickNoteDialog
          open
          onOpenChange={setLogging}
          kinds={ENTRY_KINDS}
          initialKind="call"
          title={t('log.add')}
          description={t('log.addHint')}
        />
      )}
    </>
  )
}

function Filters({
  params,
  set,
  setMany,
  search,
  setSearch,
}: {
  params: URLSearchParams
  set: (key: string, value: string) => void
  setMany: (values: Record<string, string>) => void
  search: string
  setSearch: (v: string) => void
}) {
  const { t } = useTranslation()
  const { data: people } = useUserOptions()
  const [pickingRecord, setPickingRecord] = useState(false)
  const recordName = params.get('record_name') ?? ''
  const types = (params.get('type') ?? '').split(',').filter(Boolean)
  const toggleType = (kind: string) => {
    const next = types.includes(kind) ? types.filter((k) => k !== kind) : [...types, kind]
    set('type', next.join(','))
  }
  const pickRecord = (picked: Picked | null) => {
    setPickingRecord(false)
    // One of contact / company at a time; the name is kept in the URL for the chip.
    setMany({
      contact: picked && 'contact' in picked.target ? String(picked.target.contact) : '',
      company: picked && 'company' in picked.target ? String(picked.target.company) : '',
      record_name: picked?.name ?? '',
    })
  }

  return (
    <Card className="mb-4">
      <CardContent className="grid gap-3">
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={t('log.types')}>
          {ENTRY_KINDS.map((kind) => {
            const Icon = KIND_ICONS[kind]
            const on = types.includes(kind)
            return (
              <button
                key={kind}
                type="button"
                aria-pressed={on}
                onClick={() => toggleType(kind)}
                className={cn(
                  'inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-sm transition-colors',
                  on ? 'border-primary bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted hover:text-foreground',
                )}
              >
                <Icon className="size-3.5" />
                {t(`timeline.kinds.${kind}`)}
              </button>
            )
          })}
          <label className="ms-auto flex min-w-48 flex-1 items-center gap-2 rounded-md border bg-background px-2 sm:max-w-72">
            <Search className="size-4 text-muted-foreground" />
            <input
              type="search"
              value={search}
              dir="auto"
              onChange={(e) => {
                setSearch(e.target.value)
                set('q', e.target.value.trim())
              }}
              placeholder={t('log.search')}
              aria-label={t('log.search')}
              className="h-8 min-w-0 flex-1 bg-transparent text-sm outline-none"
            />
          </label>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <FormField id="log-direction" label={t('timeline.direction')}>
            <SimpleSelect
              id="log-direction"
              value={params.get('direction') ?? ''}
              onChange={(v) => set('direction', v)}
              options={[
                { value: '', label: t('log.anyDirection') },
                { value: 'out', label: t('log.directions.out') },
                { value: 'in', label: t('log.directions.in') },
              ]}
            />
          </FormField>
          <FormField id="log-by" label={t('log.loggedBy')}>
            <SimpleSelect
              id="log-by"
              value={params.get('logged_by') ?? ''}
              onChange={(v) => set('logged_by', v)}
              options={[{ value: '', label: t('log.anyone') }, ...(people ?? []).map((u) => ({ value: String(u.id), label: u.full_name }))]}
            />
          </FormField>
          <FormField id="log-follow-up" label={t('timeline.followUp')}>
            <SimpleSelect
              id="log-follow-up"
              value={params.get('follow_up') ?? ''}
              onChange={(v) => set('follow_up', v)}
              options={['', 'any', 'open', 'done', 'none'].map((v) => ({ value: v, label: t(`log.followUps.${v || 'all'}`) }))}
            />
          </FormField>
          <FormField id="log-from" label={t('log.dateFrom')}>
            <Input id="log-from" type="date" value={params.get('date_from') ?? ''} max={params.get('date_to') || undefined} onChange={(e) => set('date_from', e.target.value)} />
          </FormField>
          <FormField id="log-to" label={t('log.dateTo')}>
            <Input id="log-to" type="date" value={params.get('date_to') ?? ''} min={params.get('date_from') || undefined} onChange={(e) => set('date_to', e.target.value)} />
          </FormField>
          <FormField id="log-record" label={t('log.record')}>
            {params.get('contact') || params.get('company') ? (
              <span className="flex h-9 items-center gap-1.5 rounded-md border bg-muted/40 ps-2.5 pe-1 text-sm">
                {params.get('contact') ? <UserRound className="size-3.5 shrink-0" /> : <Building2 className="size-3.5 shrink-0" />}
                <bdi className="min-w-0 flex-1 truncate">{recordName || '…'}</bdi>
                <Button variant="ghost" size="icon-xs" onClick={() => pickRecord(null)} aria-label={t('log.clearRecord')}>
                  <X className="size-3.5" />
                </Button>
              </span>
            ) : (
              <Button id="log-record" variant="outline" className="w-full justify-start font-normal text-muted-foreground" onClick={() => setPickingRecord(true)}>
                {t('log.anyRecord')}
              </Button>
            )}
          </FormField>
        </div>
      </CardContent>
      {pickingRecord && <RecordDialog onPick={pickRecord} onClose={() => setPickingRecord(false)} />}
    </Card>
  )
}

function RecordDialog({ onPick, onClose }: { onPick: (p: Picked) => void; onClose: () => void }) {
  const { t } = useTranslation()
  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={t('log.record')}>
      <RecordPicker onPick={onPick} idPrefix="log-record-picker" />
    </FormDialog>
  )
}

function LogRow({ item }: { item: TimelineItem }) {
  const fmt = useFormat()
  const Icon = KIND_ICONS[item.kind] ?? History
  const record = item.contact
    ? { to: `/contacts/${item.contact.id}`, name: item.contact.name, icon: UserRound }
    : item.company
      ? { to: `/companies/${item.company.id}`, name: item.company.name, icon: Building2 }
      : null
  return (
    <li className="flex gap-3 px-4 py-3">
      <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-full', KIND_STYLES[item.kind] ?? KIND_STYLES.status)}>
        <Icon className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-sm">
          <EntryTitle item={item} />
          {record && (
            <Link to={record.to} className="inline-flex items-center gap-1 text-primary hover:underline">
              <record.icon className="size-3.5" />
              <bdi>{record.name}</bdi>
            </Link>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          <time dateTime={item.occurred_at}>
            <bdi>{fmt.dateTime(item.occurred_at)}</bdi>
          </time>
          {item.created_by_name && (
            <>
              {' · '}
              <bdi>{item.created_by_name}</bdi>
            </>
          )}
        </p>
        {item.summary && <p className="mt-1 line-clamp-3 text-sm whitespace-pre-wrap [unicode-bidi:plaintext] ltr:text-left rtl:text-right">{item.summary}</p>}
        <FollowUpStatus item={item} className="mt-1.5" />
      </div>
    </li>
  )
}
