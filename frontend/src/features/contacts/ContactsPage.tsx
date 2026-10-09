import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building, Phone, Plus, Search, UsersRound, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { EmptyState, ErrorState, FormDialog, PageHeader, Pagination, SimpleSelect } from '@/components/common'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'
import { useAssignableUsers } from '@/lib/companies'
import { CONTACT_STATUSES, useCompanyOptions, useContactFacets } from '@/lib/contacts'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import type { Contact, Paginated } from '@/lib/types'
import { useDebouncedValue } from '@/lib/utils'
import { ContactForm } from './ContactForm'

const ALL = 'all'
const FILTERS = ['status', 'company', 'city', 'tag', 'assigned_to'] as const
type FilterKey = (typeof FILTERS)[number]

function TagList({ tags, max = 3 }: { tags: string[]; max?: number }) {
  if (!tags.length) return null
  return (
    <div className="flex flex-wrap gap-1">
      {tags.slice(0, max).map((tag) => (
        <Badge key={tag} variant="secondary" className="font-normal">
          {tag}
        </Badge>
      ))}
      {tags.length > max && <Badge variant="outline" className="font-normal">+{tags.length - max}</Badge>}
    </div>
  )
}

export function ContactsPage() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const canCreate = usePermission('contacts.create')
  const assignable = useAssignableUsers()
  const { data: facets } = useContactFacets()
  const { data: companies } = useCompanyOptions()

  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<Record<FilterKey, string>>({
    status: ALL,
    // "View all" from a company page links here with ?company=ID
    company: params.get('new') !== '1' && params.get('company') ? String(params.get('company')) : ALL,
    city: ALL,
    tag: ALL,
    assigned_to: ALL,
  })
  const [page, setPage] = useState(1)
  const q = useDebouncedValue(search.trim())
  // Quick-add opens the form via ?new=1 (optionally &company=ID to pre-fill it).
  const creating = params.get('new') === '1'
  const presetCompany = creating ? Number(params.get('company')) || null : null

  const setFilter = (key: FilterKey) => (value: string) => {
    setFilters((f) => ({ ...f, [key]: value }))
    setPage(1)
  }
  const active = q !== '' || FILTERS.some((k) => filters[k] !== ALL)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['contacts', 'list', { q, filters, page }],
    queryFn: async () =>
      (
        await api.get<Paginated<Contact>>('/contacts/', {
          params: {
            search: q || undefined,
            ...Object.fromEntries(FILTERS.filter((k) => filters[k] !== ALL).map((k) => [k, filters[k]])),
            page,
          },
        })
      ).data,
    placeholderData: keepPreviousData,
  })

  const closeCreate = () => setParams({}, { replace: true })

  return (
    <>
      <PageHeader
        title={t('contacts.title')}
        subtitle={t('contacts.subtitle')}
        actions={
          canCreate && (
            <Button onClick={() => setParams({ new: '1' })}>
              <Plus className="size-4" />
              {t('contacts.add')}
            </Button>
          )
        }
      />

      <div className="mb-4 grid gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
            placeholder={t('contacts.searchPlaceholder')}
            className="ps-8"
          />
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-5">
          <SimpleSelect
            value={filters.status}
            onChange={setFilter('status')}
            options={[
              { value: ALL, label: t('contacts.allStatuses') },
              ...CONTACT_STATUSES.map((s) => ({ value: s, label: t(`contacts.statuses.${s}`) })),
            ]}
          />
          <SimpleSelect
            value={filters.company}
            onChange={setFilter('company')}
            options={[
              { value: ALL, label: t('contacts.allCompanies') },
              ...(companies ?? []).map((c) => ({ value: String(c.id), label: c.name })),
            ]}
          />
          <SimpleSelect
            value={filters.city}
            onChange={setFilter('city')}
            options={[{ value: ALL, label: t('companies.allCities') }, ...(facets?.cities ?? []).map((c) => ({ value: c, label: c }))]}
          />
          <SimpleSelect
            value={filters.tag}
            onChange={setFilter('tag')}
            options={[{ value: ALL, label: t('contacts.allTags') }, ...(facets?.tags ?? []).map((c) => ({ value: c, label: c }))]}
          />
          {assignable !== null && (
            <SimpleSelect
              value={filters.assigned_to}
              onChange={setFilter('assigned_to')}
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
              setSearch('')
              setFilters({ status: ALL, company: ALL, city: ALL, tag: ALL, assigned_to: ALL })
              setPage(1)
            }}
          >
            <X className="size-3.5" />
            {t('contacts.clearFilters')}
          </Button>
        )}
      </div>

      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading ? (
        <Skeleton className="h-72 rounded-xl" />
      ) : !data?.results.length ? (
        <EmptyState
          icon={UsersRound}
          title={active ? t('common.noResults') : t('contacts.empty')}
          hint={!active && canCreate ? t('contacts.emptyHint') : undefined}
        />
      ) : (
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
                      <Link
                        to={`/contacts/${c.id}`}
                        className="font-medium hover:text-primary hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
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
          <Pagination page={page} count={data.count} onPage={setPage} />
        </>
      )}

      {creating && canCreate && (
        <FormDialog open onOpenChange={(o) => !o && closeCreate()} title={t('contacts.add')}>
          <ContactForm
            companyId={presetCompany}
            onCancel={closeCreate}
            onSaved={(contact) => {
              void queryClient.invalidateQueries({ queryKey: ['contacts'] })
              navigate(`/contacts/${contact.id}`, { replace: true })
            }}
          />
        </FormDialog>
      )}
    </>
  )
}
