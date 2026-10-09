import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ClipboardList, Search } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { EmptyState, ErrorState, PageHeader, Pagination, SimpleSelect } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useFormat } from '@/lib/format'
import type { AuditEntry, Paginated } from '@/lib/types'
import { useDebouncedValue } from '@/lib/utils'

const ACTIONS = ['create', 'update', 'delete', 'import', 'export', 'login', 'login_failed', 'logout', 'security']

const ACTION_STYLES: Record<string, string> = {
  create: 'border-success/40 text-success',
  update: 'border-primary/40 text-primary',
  delete: 'border-destructive/40 text-destructive',
  login_failed: 'border-destructive/40 text-destructive',
  security: 'border-warning/50',
  import: 'border-primary/40 text-primary',
  export: 'border-primary/40 text-primary',
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '∅'
  return String(value)
}

function Changes({ changes }: { changes: Record<string, unknown> }) {
  const { t } = useTranslation()
  const entries = Object.entries(changes ?? {})
  if (!entries.length) return <span className="text-muted-foreground">{t('admin.audit.noChanges')}</span>
  return (
    <ul className="space-y-0.5 text-xs font-latin" dir="ltr">
      {entries.slice(0, 6).map(([field, value]) => (
        <li key={field} className="break-all">
          <span className="font-medium">{field}</span>:{' '}
          {Array.isArray(value) && value.length === 2 ? (
            <>
              <span className="text-muted-foreground line-through">{formatValue(value[0])}</span> → {formatValue(value[1])}
            </>
          ) : (
            formatValue(value)
          )}
        </li>
      ))}
      {entries.length > 6 && <li className="text-muted-foreground">+{entries.length - 6}</li>}
    </ul>
  )
}

export function AuditLogPage() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const [search, setSearch] = useState('')
  const [action, setAction] = useState('all')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [page, setPage] = useState(1)
  const q = useDebouncedValue(search.trim())

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['audit-log', { q, action, from, to, page }],
    queryFn: async () =>
      (
        await api.get<Paginated<AuditEntry>>('/audit-log/', {
          params: {
            search: q || undefined,
            action: action === 'all' ? undefined : action,
            date_from: from || undefined,
            date_to: to || undefined,
            page,
          },
        })
      ).data,
    placeholderData: keepPreviousData,
  })

  const actionBadge = (e: AuditEntry) => (
    <Badge variant="outline" className={ACTION_STYLES[e.action]}>
      {e.action_label}
    </Badge>
  )

  return (
    <>
      <PageHeader title={t('admin.audit.title')} subtitle={t('admin.audit.subtitle')} />
      <div className="mb-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_12rem_13rem_13rem]">
        <div className="relative">
          <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }} placeholder={t('admin.audit.searchPlaceholder')} className="ps-8" />
        </div>
        <SimpleSelect
          value={action}
          onChange={(v) => {
            setAction(v)
            setPage(1)
          }}
          options={[{ value: 'all', label: t('admin.audit.allActions') }, ...ACTIONS.map((a) => ({ value: a, label: t(`admin.audit.actions.${a}`) }))]}
        />
        <div className="flex items-center gap-2">
          <Label htmlFor="from" className="shrink-0 text-xs text-muted-foreground">
            {t('admin.audit.from')}
          </Label>
          <Input id="from" type="date" value={from} onChange={(e) => {
            setFrom(e.target.value)
            setPage(1)
          }} />
        </div>
        <div className="flex items-center gap-2">
          <Label htmlFor="to" className="shrink-0 text-xs text-muted-foreground">
            {t('admin.audit.to')}
          </Label>
          <Input id="to" type="date" value={to} onChange={(e) => {
            setTo(e.target.value)
            setPage(1)
          }} />
        </div>
      </div>

      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading ? (
        <Skeleton className="h-96 rounded-xl" />
      ) : !data?.results.length ? (
        <EmptyState icon={ClipboardList} title={t('common.noResults')} />
      ) : (
        <>
          <Card className="hidden py-0 md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('admin.audit.when')}</TableHead>
                  <TableHead>{t('admin.audit.who')}</TableHead>
                  <TableHead>{t('admin.audit.action')}</TableHead>
                  <TableHead>{t('admin.audit.record')}</TableHead>
                  <TableHead>{t('admin.audit.changes')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.results.map((e) => (
                  <TableRow key={e.id} className="align-top">
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {fmt.dateTime(e.timestamp)}
                      {e.ip && <p className="text-xs font-latin">{e.ip}</p>}
                    </TableCell>
                    <TableCell>{e.actor_name ?? t('admin.audit.system')}</TableCell>
                    <TableCell>{actionBadge(e)}</TableCell>
                    <TableCell className="max-w-48">
                      <p className="truncate font-medium">{e.object_repr || '—'}</p>
                      <p className="text-xs text-muted-foreground capitalize">{e.model_label}</p>
                      {e.description && <p className="text-xs text-muted-foreground">{e.description}</p>}
                    </TableCell>
                    <TableCell className="max-w-md whitespace-normal">
                      <Changes changes={e.changes} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>

          <ul className="grid gap-2 md:hidden">
            {data.results.map((e) => (
              <li key={e.id}>
                <Card className="gap-2 px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    {actionBadge(e)}
                    <span className="text-xs text-muted-foreground">{fmt.relative(e.timestamp)}</span>
                  </div>
                  <p className="text-sm">
                    <span className="font-medium">{e.actor_name ?? t('admin.audit.system')}</span>
                    {e.object_repr && <> · {e.object_repr}</>}
                    {e.model_label && <span className="text-muted-foreground"> ({e.model_label})</span>}
                  </p>
                  {e.description && <p className="text-xs text-muted-foreground">{e.description}</p>}
                  {e.action === 'update' && <Changes changes={e.changes} />}
                </Card>
              </li>
            ))}
          </ul>
          <Pagination page={page} count={data.count} onPage={setPage} />
        </>
      )}
    </>
  )
}
