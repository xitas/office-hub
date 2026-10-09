import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Building, Phone, Search, UsersRound, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { EmptyState, ErrorState, Pagination, SimpleSelect } from '@/components/common'
import { StatusBadge } from '@/components/common/StatusBadge'
import { TagList } from '@/components/common/TagList'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAssignableUsers } from '@/lib/companies'
import { ALL, CONTACT_FILTER_KEYS, CONTACT_STATUSES, filterParams, useCompanyOptions, useContactFacets, type ContactFilters, type ContactFilterKey } from '@/lib/contacts'
import { useFormat } from '@/lib/format'
import type { Contact, Paginated } from '@/lib/types'
import { cn } from '@/lib/utils'

/** Search box + filter selects shared by the Contacts page and the Pipeline. */
export function ContactFilterBar({
  search,
  onSearch,
  filters,
  onFilters,
  hide = [],
}: {
  search: string
  onSearch: (value: string) => void
  filters: ContactFilters
  onFilters: (filters: ContactFilters) => void
  /** Filters not shown here (e.g. status on the board, where every status is a column). */
  hide?: ContactFilterKey[]
}) {
  const { t } = useTranslation()
  const assignable = useAssignableUsers()
  const { data: facets } = useContactFacets()
  const { data: companies } = useCompanyOptions()
  const set = (key: ContactFilterKey) => (value: string) => onFilters({ ...filters, [key]: value })
  const shown = (key: ContactFilterKey) => !hide.includes(key) && (key !== 'assigned_to' || assignable !== null)
  const active = search.trim() !== '' || CONTACT_FILTER_KEYS.some((k) => shown(k) && filters[k] !== ALL)
  const count = CONTACT_FILTER_KEYS.filter(shown).length

  return (
    <div className="mb-4 grid gap-2">
      <div className="relative">
        <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={search} onChange={(e) => onSearch(e.target.value)} placeholder={t('contacts.searchPlaceholder')} className="ps-8" />
      </div>
      <div className={cn('grid grid-cols-2 gap-2 md:grid-cols-3', count >= 5 ? 'lg:grid-cols-5' : 'lg:grid-cols-4')}>
        {shown('status') && (
          <SimpleSelect
            value={filters.status}
            onChange={set('status')}
            options={[
              { value: ALL, label: t('contacts.allStatuses') },
              ...CONTACT_STATUSES.map((s) => ({ value: s, label: t(`contacts.statuses.${s}`) })),
            ]}
          />
        )}
        {shown('company') && (
          <SimpleSelect
            value={filters.company}
            onChange={set('company')}
            options={[
              { value: ALL, label: t('contacts.allCompanies') },
              ...(companies ?? []).map((c) => ({ value: String(c.id), label: c.name })),
            ]}
          />
        )}
        {shown('city') && (
          <SimpleSelect
            value={filters.city}
            onChange={set('city')}
            options={[{ value: ALL, label: t('companies.allCities') }, ...(facets?.cities ?? []).map((c) => ({ value: c, label: c }))]}
          />
        )}
        {shown('tag') && (
          <SimpleSelect
            value={filters.tag}
            onChange={set('tag')}
            options={[{ value: ALL, label: t('contacts.allTags') }, ...(facets?.tags ?? []).map((c) => ({ value: c, label: c }))]}
          />
        )}
        {shown('assigned_to') && assignable && (
          <SimpleSelect
            value={filters.assigned_to}
            onChange={set('assigned_to')}
            options={[
              { value: ALL, label: t('companies.anyone') },
              ...assignable.map((u) => ({ value: String(u.id), label: u.full_name })),
            ]}
          />
        )}
      </div>
      {active && (
        <Button
          variant="ghost"
          size="sm"
          className="justify-self-start"
          onClick={() => {
            onSearch('')
            onFilters(Object.fromEntries(CONTACT_FILTER_KEYS.map((k) => [k, hide.includes(k) ? filters[k] : ALL])) as ContactFilters)
          }}
        >
          <X className="size-3.5" />
          {t('contacts.clearFilters')}
        </Button>
      )}
    </div>
  )
}

/** Paginated contacts as a table (desktop) or cards (phone). */
export function ContactResults({
  search,
  filters,
  page,
  onPage,
  emptyHint,
}: {
  search: string
  filters: ContactFilters
  page: number
  onPage: (page: number) => void
  emptyHint?: string
}) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const navigate = useNavigate()
  const active = search !== '' || CONTACT_FILTER_KEYS.some((k) => filters[k] !== ALL)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['contacts', 'list', { search, filters, page }],
    queryFn: async () =>
      (await api.get<Paginated<Contact>>('/contacts/', { params: { search: search || undefined, ...filterParams(filters), page } })).data,
    placeholderData: keepPreviousData,
  })

  if (isError) return <ErrorState onRetry={() => void refetch()} />
  if (isLoading) return <Skeleton className="h-72 rounded-xl" />
  if (!data?.results.length)
    return (
      <EmptyState icon={UsersRound} title={active ? t('common.noResults') : t('contacts.empty')} hint={active ? undefined : emptyHint} />
    )

  return (
    <>
      {/* Desktop table */}
      <Card className="hidden py-0 md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('common.name')}</TableHead>
              <TableHead>{t('contacts.status')}</TableHead>
              <TableHead>{t('common.phone')}</TableHead>
              <TableHead>{t('companies.city')}</TableHead>
              <TableHead>{t('contacts.tags')}</TableHead>
              <TableHead>{t('companies.assignedTo')}</TableHead>
              <TableHead>{t('companies.updated')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.results.map((c) => (
              <TableRow key={c.id} className="cursor-pointer" onClick={() => navigate(`/contacts/${c.id}`)}>
                <TableCell>
                  <Link to={`/contacts/${c.id}`} className="font-medium hover:text-primary hover:underline" onClick={(e) => e.stopPropagation()}>
                    {c.full_name}
                  </Link>
                  {(c.company_name || c.job_title) && (
                    <p className="text-xs text-muted-foreground">{[c.job_title, c.company_name].filter(Boolean).join(' · ')}</p>
                  )}
                </TableCell>
                <TableCell>
                  <StatusBadge status={c.status} />
                </TableCell>
                <TableCell className="font-latin" dir="ltr">
                  {c.phone || '—'}
                </TableCell>
                <TableCell>{c.city || '—'}</TableCell>
                <TableCell className="max-w-48">
                  <TagList tags={c.tags} max={2} />
                </TableCell>
                <TableCell>{c.assigned_to_name ?? <span className="text-muted-foreground">{t('companies.unassigned')}</span>}</TableCell>
                <TableCell className="text-muted-foreground">{fmt.relative(c.updated_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      {/* Phone cards */}
      <ul className="grid gap-2 md:hidden">
        {data.results.map((c) => (
          <li key={c.id}>
            <Link to={`/contacts/${c.id}`} className="block rounded-xl focus-visible:ring-2 focus-visible:ring-ring">
              <Card className="gap-1.5 px-4 py-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 truncate font-medium">{c.full_name}</p>
                  <StatusBadge status={c.status} className="shrink-0" />
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  {c.company_name && (
                    <span className="flex items-center gap-1">
                      <Building className="size-3.5" />
                      {c.company_name}
                    </span>
                  )}
                  {c.phone && (
                    <span className="flex items-center gap-1 font-latin" dir="ltr">
                      <Phone className="size-3.5" />
                      {c.phone}
                    </span>
                  )}
                </div>
                <TagList tags={c.tags} />
                <p className="text-xs text-muted-foreground">
                  {c.assigned_to_name ?? t('companies.unassigned')} · {fmt.relative(c.updated_at)}
                </p>
              </Card>
            </Link>
          </li>
        ))}
      </ul>
      <Pagination page={page} count={data.count} onPage={onPage} />
    </>
  )
}
