import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Building2, Loader2, Pencil, Plus, Trash2, Users } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { EmptyState, ErrorState, FormDialog, FormField, PageHeader, SimpleSelect, TextField } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { useConfirm } from '@/lib/confirm'
import { useDepartments, useUserOptions } from '@/lib/queries'
import type { Department } from '@/lib/types'

export function DepartmentsPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const confirm = useConfirm()
  const { data, isLoading, isError, refetch } = useDepartments()
  const [editing, setEditing] = useState<Department | 'new' | null>(null)

  const remove = useMutation({
    mutationFn: (d: Department) => api.delete(`/departments/${d.id}/`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['departments'] })
      toast.success(t('common.deleted'))
    },
    onError: (err) => toast.error(apiError(err).message),
  })

  return (
    <>
      <PageHeader
        title={t('admin.departments.title')}
        subtitle={t('admin.departments.subtitle')}
        actions={
          <Button onClick={() => setEditing('new')}>
            <Plus className="size-4" />
            {t('admin.departments.add')}
          </Button>
        }
      />
      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-40 rounded-xl" />
          ))}
        </div>
      ) : !data?.length ? (
        <EmptyState icon={Building2} title={t('common.noResults')} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {data.map((d) => (
            <Card key={d.id}>
              <CardHeader>
                <CardTitle>{d.name}</CardTitle>
                {d.description && <CardDescription className="line-clamp-2">{d.description}</CardDescription>}
              </CardHeader>
              <CardContent className="grid gap-1 text-sm">
                <p className="text-muted-foreground">
                  {t('common.manager')}: <span className="text-foreground">{d.manager_name ?? t('admin.departments.noManager')}</span>
                </p>
                <p className="flex items-center gap-1.5 text-muted-foreground">
                  <Users className="size-3.5" />
                  {t('common.members')}: <span className="text-foreground font-latin">{d.member_count}</span>
                </p>
              </CardContent>
              <CardFooter className="justify-end gap-1">
                <Button variant="ghost" size="sm" onClick={() => setEditing(d)}>
                  <Pencil className="size-3.5" />
                  {t('common.edit')}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive"
                  onClick={async () => {
                    const ok = await confirm({
                      title: t('admin.departments.deleteTitle', { name: d.name }),
                      description: t('admin.departments.deleteHint'),
                      confirmLabel: t('common.delete'),
                      destructive: true,
                    })
                    if (ok) remove.mutate(d)
                  }}
                >
                  <Trash2 className="size-3.5" />
                  {t('common.delete')}
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      )}

      {editing && (
        <DepartmentDialog
          department={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            void queryClient.invalidateQueries({ queryKey: ['departments'] })
            setEditing(null)
          }}
        />
      )}
    </>
  )
}

function DepartmentDialog({
  department,
  onClose,
  onSaved,
}: {
  department: Department | null
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useTranslation()
  const { data: users } = useUserOptions()
  const [name, setName] = useState(department?.name ?? '')
  const [description, setDescription] = useState(department?.description ?? '')
  const [manager, setManager] = useState(department?.manager ? String(department.manager) : 'none')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErrors({})
    const payload = { name, description, manager: manager === 'none' ? null : Number(manager) }
    try {
      if (department) await api.patch(`/departments/${department.id}/`, payload)
      else await api.post('/departments/', payload)
      toast.success(department ? t('common.saved') : t('common.created'))
      onSaved()
    } catch (err) {
      const info = apiError(err)
      setErrors(info.fields)
      if (!Object.keys(info.fields).length) toast.error(info.message)
    } finally {
      setBusy(false)
    }
  }

  const managerOptions = (users ?? []).filter((u) => u.role !== 'staff')

  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={department ? t('admin.departments.edit') : t('admin.departments.add')}
    >
      <form onSubmit={submit} className="grid gap-4">
        <TextField id="d-name" label={t('common.name')} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} required />
        <FormField id="d-desc" label={t('common.description')} error={errors.description}>
          <Textarea id="d-desc" value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
        </FormField>
        <FormField id="d-manager" label={t('common.manager')} error={errors.manager}>
          <SimpleSelect
            id="d-manager"
            value={manager}
            onChange={setManager}
            options={[
              { value: 'none', label: t('admin.departments.noManager') },
              ...managerOptions.map((u) => ({ value: String(u.id), label: `${u.full_name} (${t(`roles.${u.role}`)})` })),
            ]}
          />
        </FormField>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={busy}>
            {busy && <Loader2 className="size-4 animate-spin" />}
            {department ? t('common.save') : t('common.create')}
          </Button>
        </div>
      </form>
    </FormDialog>
  )
}
