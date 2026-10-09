import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, MapPin, Phone, Plus, Search } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { EmptyState, ErrorState, FormDialog, PageHeader, Pagination, SimpleSelect } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'
import { INDUSTRIES, useAssignableUsers, useCompanyFacets } from '@/lib/companies'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import type { Company, Paginated } from '@/lib/types'
import { useDebouncedValue } from '@/lib/utils'
import { TransferButtons } from '@/features/transfer/TransferButtons'
import { CompanyForm } from './CompanyForm'

const ALL = 'all'

export function CompaniesPage() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const canCreate = usePermission('contacts.create')
  const assignable = useAssignableUsers()
  const { data: facets } = useCompanyFacets()

  const [search, setSearch] = useState('')
  const [city, setCity] = useState(ALL)
  const [industry, setIndustry] = useState(ALL)
  const [assignee, setAssignee] = useState(ALL)
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const q = useDebouncedValue(search.trim())
  const filter = (setter: (v: string) => void) => (v: string) => {
    setter(v)
    setPage(1)
  }

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['companies', 'list', { q, city, industry, assignee, page }],
    queryFn: async () =>
      (
        await api.get<Paginated<Company>>('/companies/', {
          params: {
            search: q || undefined,
            city: city === ALL ? undefined : city,
            industry: industry === ALL ? undefined : industry,
            assigned_to: assignee === ALL ? undefined : assignee,
            page,
          },
        })
      ).data,
    placeholderData: keepPreviousData,
  })

  const industryName = (c: Company) => (c.industry ? t(`companies.industries.${c.industry}`) : '—')

  return (
    <>
      <PageHeader
        title={t('companies.title')}
        subtitle={t('companies.subtitle')}
        actions={
          <>
            <TransferButtons
              kind="companies"
              params={{
                search: q || undefined,
                city: city === ALL ? undefined : city,
                industry: industry === ALL ? undefined : industry,
                assigned_to: assignee === ALL ? undefined : assignee,
              }}
            />
            {canCreate && (
              <Button onClick={() => setCreating(true)}>
                <Plus className="size-4" />
                {t('companies.add')}
              </Button>
            )}
          </>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-2 lg:grid-cols-[minmax(0,1fr)_11rem_13rem_13rem]">
        <div className="relative col-span-2 lg:col-span-1">
          <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => filter(setSearch)(e.target.value)}
            placeholder={t('companies.searchPlaceholder')}
            className="ps-8"
          />
        </div>
        <SimpleSelect
          value={city}
          onChange={filter(setCity)}
          options={[{ value: ALL, label: t('companies.allCities') }, ...(facets?.cities ?? []).map((c) => ({ value: c, label: c }))]}
        />
        <SimpleSelect
          value={industry}
          onChange={filter(setIndustry)}
          options={[
            { value: ALL, label: t('companies.allIndustries') },
            ...INDUSTRIES.map((i) => ({ value: i, label: t(`companies.industries.${i}`) })),
          ]}
        />
        {assignable !== null && (
          <SimpleSelect
            className="col-span-2 lg:col-span-1"
            value={assignee}
            onChange={filter(setAssignee)}
            options={[
              { value: ALL, label: t('companies.anyone') },
              ...assignable.map((u) => ({ value: String(u.id), label: u.full_name })),
            ]}
          />
        )}
      </div>

      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading ? (
        <Skeleton className="h-72 rounded-xl" />
      ) : !data?.results.length ? (
        <EmptyState
          icon={Building2}
          title={q || city !== ALL || industry !== ALL || assignee !== ALL ? t('common.noResults') : t('companies.empty')}
          hint={canCreate ? t('companies.emptyHint') : undefined}
        />
      ) : (
        <>
          {/* Desktop table */}
          <Card className="hidden py-0 md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('companies.name')}</TableHead>
                  <TableHead>{t('companies.industry')}</TableHead>
                  <TableHead>{t('companies.city')}</TableHead>
                  <TableHead>{t('common.phone')}</TableHead>
                  <TableHead>{t('companies.assignedTo')}</TableHead>
                  <TableHead>{t('companies.updated')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.results.map((c) => (
                  <TableRow key={c.id} className="cursor-pointer" onClick={() => navigate(`/companies/${c.id}`)}>
                    <TableCell className="font-medium">
                      <Link to={`/companies/${c.id}`} className="hover:text-primary hover:underline" onClick={(e) => e.stopPropagation()}>
                        {c.name}
                      </Link>
                    </TableCell>
                    <TableCell>{industryName(c)}</TableCell>
                    <TableCell>{c.city || '—'}</TableCell>
                    <TableCell className="font-latin" dir="ltr">
                      {c.phone || '—'}
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
                <Link to={`/companies/${c.id}`} className="block rounded-xl focus-visible:ring-2 focus-visible:ring-ring">
                  <Card className="gap-1.5 px-4 py-3">
                    <div className="flex items-start justify-between gap-2">
                      <p className="min-w-0 truncate font-medium">{c.name}</p>
                      {c.industry && (
                        <Badge variant="secondary" className="shrink-0">
                          {industryName(c)}
                        </Badge>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      {c.city && (
                        <span className="flex items-center gap-1">
                          <MapPin className="size-3.5" />
                          {c.city}
                        </span>
                      )}
                      {c.phone && (
                        <span className="flex items-center gap-1 font-latin" dir="ltr">
                          <Phone className="size-3.5" />
                          {c.phone}
                        </span>
                      )}
                    </div>
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

      {creating && (
        <FormDialog open onOpenChange={(o) => !o && setCreating(false)} title={t('companies.add')}>
          <CompanyForm
            onCancel={() => setCreating(false)}
            onSaved={(company) => {
              void queryClient.invalidateQueries({ queryKey: ['companies'] })
              setCreating(false)
              navigate(`/companies/${company.id}`)
            }}
          />
        </FormDialog>
      )}
    </>
  )
}
