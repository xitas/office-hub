import { useQuery } from '@tanstack/react-query'
import { AlarmClock, CheckSquare, Search, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { EmptyState, ErrorState, PageHeader, Pagination, RoleBadge, SimpleSelect, UserAvatar } from '@/components/common'
import { ContactButtons } from '@/components/common/ContactButtons'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { useDepartments } from '@/lib/queries'
import type { Paginated, User, WorkloadRow } from '@/lib/types'
import { cn, useDebouncedValue } from '@/lib/utils'

const PAGE_SIZE = 24

/** Open and overdue tasks per person, for managers and admins (counted over the tasks they can see). */
function useWorkload() {
  const me = useMe()
  const allowed = me.role === 'admin' || me.role === 'manager'
  const { data } = useQuery({
    queryKey: ['tasks', 'workload'],
    queryFn: async () => (await api.get<WorkloadRow[]>('/tasks/workload/')).data,
    enabled: allowed,
    staleTime: 60_000,
  })
  return allowed ? new Map((data ?? []).map((r) => [r.user_id, r])) : null
}

export function TeamPage() {
  const { t } = useTranslation()
  // Department and highlighted user live in the URL so search results can deep-link here.
  const [params, setParams] = useSearchParams()
  const highlight = Number(params.get('user')) || null
  const department = params.get('department') ?? 'all'
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const q = useDebouncedValue(search.trim())
  const { data: departments } = useDepartments()
  const workload = useWorkload()

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['users', 'directory', { q, department, page }],
    queryFn: async () =>
      (
        await api.get<Paginated<User>>('/users/', {
          params: {
            search: q || undefined,
            department: department === 'all' ? undefined : department,
            page,
            page_size: PAGE_SIZE,
          },
        })
      ).data,
  })

  // The highlighted person may be on another page (or filtered out): fetch them directly.
  const onThisPage = !!data?.results.some((u) => u.id === highlight)
  const { data: spotlight } = useQuery({
    queryKey: ['users', 'detail', highlight],
    queryFn: async () => (await api.get<User>(`/users/${highlight}/`)).data,
    enabled: !!highlight && !!data && !onThisPage,
  })

  useEffect(() => {
    if (highlight) document.getElementById(`user-${highlight}`)?.scrollIntoView({ block: 'center' })
  }, [highlight, data, spotlight])

  const setDepartment = (value: string) => {
    setPage(1)
    setParams(value === 'all' ? {} : { department: value }, { replace: true })
  }

  return (
    <>
      <PageHeader title={t('team.title')} subtitle={t('team.subtitle')} />
      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
            placeholder={t('team.searchPlaceholder')}
            className="ps-8"
          />
        </div>
        <SimpleSelect
          className="sm:w-56"
          value={department}
          onChange={setDepartment}
          options={[
            { value: 'all', label: t('team.allDepartments') },
            ...(departments ?? []).map((d) => ({ value: String(d.id), label: d.name })),
          ]}
        />
      </div>

      {highlight && spotlight && !onThisPage && (
        <div className="mb-4 sm:max-w-md">
          <MemberCard user={spotlight} highlighted workload={workload?.get(spotlight.id)} />
        </div>
      )}

      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-36 rounded-xl" />
          ))}
        </div>
      ) : !data?.results.length ? (
        <EmptyState icon={Users} title={t('common.noResults')} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {data.results.map((u) => (
              <MemberCard key={u.id} user={u} highlighted={highlight === u.id} workload={workload?.get(u.id)} />
            ))}
          </div>
          <Pagination page={page} count={data.count} pageSize={PAGE_SIZE} onPage={setPage} />
        </>
      )}
    </>
  )
}

function MemberCard({ user: u, highlighted, workload }: { user: User; highlighted?: boolean; workload?: WorkloadRow }) {
  const { t } = useTranslation()
  return (
    <Card id={`user-${u.id}`} className={cn(highlighted && 'ring-2 ring-primary')}>
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-start gap-3">
          <UserAvatar name={u.full_name} src={u.avatar} className="size-11" />
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">{u.full_name}</p>
            <p className="truncate text-xs text-muted-foreground">
              {[u.job_title, u.department_name].filter(Boolean).join(' · ') || t('common.noDepartment')}
            </p>
            <div className="mt-1">
              <RoleBadge role={u.role} />
            </div>
          </div>
        </div>
        {workload && (
          <Link
            to={`/tasks?view=all&assignee=${u.id}`}
            className="flex items-center gap-3 text-xs text-muted-foreground hover:text-foreground"
            title={t('team.tasksTitle')}
          >
            <span className="inline-flex items-center gap-1">
              <CheckSquare className="size-3.5" />
              {t('team.openTasks', { count: workload.open })}
            </span>
            {workload.overdue > 0 && (
              <span className="inline-flex items-center gap-1 font-medium text-destructive">
                <AlarmClock className="size-3.5" />
                {t('team.overdueTasks', { count: workload.overdue })}
              </span>
            )}
          </Link>
        )}
        <ContactButtons phone={u.phone} email={u.email} />
      </CardContent>
    </Card>
  )
}
