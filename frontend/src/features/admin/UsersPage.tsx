import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, MoreHorizontal, Pencil, Plus, Search, ShieldCheck, Trash2, UserCheck, UserX, Users } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  EmptyState,
  ErrorState,
  FormDialog,
  FormField,
  PageHeader,
  Pagination,
  RoleBadge,
  SimpleSelect,
  TextField,
  UserAvatar,
} from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { useConfirm } from '@/lib/confirm'
import { useFormat } from '@/lib/format'
import { useDepartments } from '@/lib/queries'
import type { Paginated, Role, User } from '@/lib/types'
import { cn, useDebouncedValue } from '@/lib/utils'

const ROLES: Role[] = ['admin', 'manager', 'staff']

export function UsersPage() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const me = useMe()
  const queryClient = useQueryClient()
  const confirm = useConfirm()
  const [search, setSearch] = useState('')
  const [role, setRole] = useState('all')
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<User | 'new' | null>(null)
  const q = useDebouncedValue(search.trim())

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['users', 'admin', { q, role, page }],
    queryFn: async () =>
      (
        await api.get<Paginated<User>>('/users/', {
          params: { search: q || undefined, role: role === 'all' ? undefined : role, page, ordering: 'full_name' },
        })
      ).data,
    placeholderData: keepPreviousData,
  })

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['users'] })

  const toggleActive = useMutation({
    mutationFn: (u: User) => api.patch(`/users/${u.id}/`, { is_active: !u.is_active }),
    onSuccess: () => {
      invalidate()
      toast.success(t('common.saved'))
    },
    onError: (err) => toast.error(apiError(err).message),
  })

  const remove = useMutation({
    mutationFn: (u: User) => api.delete(`/users/${u.id}/`),
    onSuccess: () => {
      invalidate()
      toast.success(t('common.deleted'))
    },
    onError: (err) => toast.error(apiError(err).message),
  })

  const actions = (u: User) => (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" aria-label={t('common.actions')} />}>
        <MoreHorizontal className="size-4" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => setEditing(u)}>
          <Pencil className="size-4" />
          {t('common.edit')}
        </DropdownMenuItem>
        {u.id !== me.id && (
          <>
            <DropdownMenuItem onClick={() => toggleActive.mutate(u)}>
              {u.is_active ? <UserX className="size-4" /> : <UserCheck className="size-4" />}
              {u.is_active ? t('admin.users.deactivate') : t('admin.users.activate')}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              onClick={async () => {
                const ok = await confirm({
                  title: t('admin.users.deleteTitle', { name: u.full_name }),
                  description: t('admin.users.deleteHint'),
                  confirmLabel: t('common.delete'),
                  destructive: true,
                })
                if (ok) remove.mutate(u)
              }}
            >
              <Trash2 className="size-4" />
              {t('common.delete')}
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )

  return (
    <>
      <PageHeader
        title={t('admin.users.title')}
        subtitle={t('admin.users.subtitle')}
        actions={
          <Button onClick={() => setEditing('new')}>
            <Plus className="size-4" />
            {t('admin.users.add')}
          </Button>
        }
      />

      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }} placeholder={t('admin.users.searchPlaceholder')} className="ps-8" />
        </div>
        <SimpleSelect
          className="sm:w-44"
          value={role}
          onChange={(v) => {
            setRole(v)
            setPage(1)
          }}
          options={[{ value: 'all', label: t('admin.users.allRoles') }, ...ROLES.map((r) => ({ value: r, label: t(`roles.${r}`) }))]}
        />
      </div>

      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : !data?.results.length ? (
        <EmptyState icon={Users} title={t('common.noResults')} />
      ) : (
        <>
          {/* Desktop table */}
          <Card className="hidden py-0 md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('common.name')}</TableHead>
                  <TableHead>{t('common.role')}</TableHead>
                  <TableHead>{t('common.department')}</TableHead>
                  <TableHead>{t('admin.users.lastLogin')}</TableHead>
                  <TableHead>{t('common.status')}</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.results.map((u) => (
                  <TableRow key={u.id} className={cn(!u.is_active && 'opacity-60')}>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <UserAvatar name={u.full_name} src={u.avatar} className="size-8" />
                        <div className="min-w-0">
                          <p className="flex items-center gap-1.5 font-medium">
                            {u.full_name}
                            {u.two_factor_enabled && <ShieldCheck className="size-3.5 text-success" aria-label="2FA" />}
                          </p>
                          <p className="text-xs text-muted-foreground font-latin">{u.email}</p>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <RoleBadge role={u.role} />
                    </TableCell>
                    <TableCell>{u.department_name ?? '—'}</TableCell>
                    <TableCell className="text-muted-foreground">{u.last_login ? fmt.relative(u.last_login) : t('common.never')}</TableCell>
                    <TableCell>
                      <Badge variant={u.is_active ? 'outline' : 'secondary'}>
                        {u.is_active ? t('common.active') : t('common.inactive')}
                      </Badge>
                    </TableCell>
                    <TableCell>{actions(u)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>

          {/* Mobile cards */}
          <ul className="grid gap-2 md:hidden">
            {data.results.map((u) => (
              <li key={u.id}>
                <Card className={cn('flex-row items-center gap-3 px-4 py-3', !u.is_active && 'opacity-60')}>
                  <UserAvatar name={u.full_name} src={u.avatar} className="size-10" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{u.full_name}</p>
                    <p className="truncate text-xs text-muted-foreground">{u.department_name ?? t('common.noDepartment')}</p>
                    <div className="mt-1 flex gap-1">
                      <RoleBadge role={u.role} />
                      {!u.is_active && <Badge variant="secondary">{t('common.inactive')}</Badge>}
                    </div>
                  </div>
                  {actions(u)}
                </Card>
              </li>
            ))}
          </ul>
          <Pagination page={page} count={data.count} onPage={setPage} />
        </>
      )}

      {editing && (
        <UserFormDialog
          user={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            invalidate()
            setEditing(null)
          }}
        />
      )}
    </>
  )
}

function UserFormDialog({ user, onClose, onSaved }: { user: User | null; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation()
  const me = useMe()
  const { data: departments } = useDepartments()
  const [form, setForm] = useState({
    full_name: user?.full_name ?? '',
    email: user?.email ?? '',
    phone: user?.phone ?? '',
    job_title: user?.job_title ?? '',
    role: user?.role ?? 'staff',
    department: user?.department ? String(user.department) : 'none',
    password: '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const set = (key: keyof typeof form) => (value: string) => setForm((f) => ({ ...f, [key]: value }))
  const isSelf = user?.id === me.id

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErrors({})
    const payload: Record<string, unknown> = {
      ...form,
      department: form.department === 'none' ? null : Number(form.department),
    }
    if (!form.password) delete payload.password
    try {
      if (user) await api.patch(`/users/${user.id}/`, payload)
      else await api.post('/users/', payload)
      toast.success(user ? t('common.saved') : t('common.created'))
      onSaved()
    } catch (err) {
      const info = apiError(err)
      setErrors(info.fields)
      if (!Object.keys(info.fields).length) toast.error(info.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={user ? t('admin.users.edit') : t('admin.users.add')}>
      <form onSubmit={submit} className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField id="u-name" label={t('common.name')} value={form.full_name} onChange={(e) => set('full_name')(e.target.value)} error={errors.full_name} required />
          <TextField id="u-email" type="email" label={t('common.email')} value={form.email} onChange={(e) => set('email')(e.target.value)} error={errors.email} required dir="ltr" />
          <TextField id="u-phone" label={t('common.phone')} value={form.phone} onChange={(e) => set('phone')(e.target.value)} error={errors.phone} dir="ltr" inputMode="tel" />
          <TextField id="u-title" label={t('common.jobTitle')} value={form.job_title} onChange={(e) => set('job_title')(e.target.value)} error={errors.job_title} />
          <FormField id="u-role" label={t('common.role')} error={errors.role}>
            <SimpleSelect
              id="u-role"
              value={form.role}
              onChange={set('role')}
              disabled={isSelf}
              options={ROLES.map((r) => ({ value: r, label: t(`roles.${r}`) }))}
            />
          </FormField>
          <FormField id="u-dept" label={t('common.department')} error={errors.department}>
            <SimpleSelect
              id="u-dept"
              value={form.department}
              onChange={set('department')}
              options={[
                { value: 'none', label: t('common.noDepartment') },
                ...(departments ?? []).map((d) => ({ value: String(d.id), label: d.name })),
              ]}
            />
          </FormField>
        </div>
        <TextField
          id="u-password"
          type="password"
          label={t('admin.users.password')}
          value={form.password}
          onChange={(e) => set('password')(e.target.value)}
          error={errors.password}
          hint={user ? t('admin.users.passwordEditHint') : undefined}
          required={!user}
          autoComplete="new-password"
          dir="ltr"
        />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={busy}>
            {busy && <Loader2 className="size-4 animate-spin" />}
            {user ? t('common.save') : t('common.create')}
          </Button>
        </div>
      </form>
    </FormDialog>
  )
}
