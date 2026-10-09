import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Building2, Globe, Mail, MapPin, Pencil, Phone, Trash2, UserRound } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState } from '@/components/common'
import { ContactButtons } from '@/components/common/ContactButtons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { api, apiError } from '@/lib/api'
import { useConfirm } from '@/lib/confirm'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import type { Company } from '@/lib/types'
import { CompanyContacts } from '@/features/contacts/CompanyContacts'
import { Timeline } from '@/features/timeline/Timeline'
import { CompanyForm } from './CompanyForm'

function Detail({ icon: Icon, label, children }: { icon: typeof Phone; label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground">{label}</p>
        <div className="text-sm break-words">{children}</div>
      </div>
    </div>
  )
}

export function CompanyDetailPage() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const confirm = useConfirm()
  const canEdit = usePermission('contacts.edit')
  const canDelete = usePermission('contacts.delete')
  const [editing, setEditing] = useState(false)

  const { data: company, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['companies', 'detail', id],
    queryFn: async () => (await api.get<Company>(`/companies/${id}/`)).data,
    retry: false,
  })

  const remove = useMutation({
    mutationFn: () => api.delete(`/companies/${id}/`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['companies'] })
      toast.success(t('common.deleted'))
      navigate('/companies')
    },
    onError: (err) => toast.error(apiError(err).message),
  })

  const back = (
    <Button variant="ghost" size="sm" className="-ms-2 mb-3" nativeButton={false} render={<Link to="/companies" />}>
      <ArrowLeft className="size-4 rtl:rotate-180" />
      {t('companies.back')}
    </Button>
  )

  if (isLoading) return <Skeleton className="h-96 max-w-3xl rounded-xl" />
  if (isError || !company) {
    const notFound = (error as { response?: { status?: number } } | null)?.response?.status === 404
    return (
      <>
        {back}
        {notFound ? (
          <EmptyState icon={Building2} title={t('companies.notFound')} hint={t('companies.notFoundHint')} />
        ) : (
          <ErrorState onRetry={() => void refetch()} />
        )}
      </>
    )
  }

  const saved = (updated: Company) => {
    queryClient.setQueryData(['companies', 'detail', id], updated)
    void queryClient.invalidateQueries({ queryKey: ['companies', 'list'] })
    void queryClient.invalidateQueries({ queryKey: ['companies', 'facets'] })
    setEditing(false)
  }

  const askDelete = async () => {
    const ok = await confirm({
      title: t('companies.deleteTitle', { name: company.name }),
      description: t('companies.deleteHint'),
      confirmLabel: t('common.delete'),
      destructive: true,
    })
    if (ok) remove.mutate()
  }

  return (
    <div className="max-w-3xl">
      {back}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Building2 className="size-6" />
          </div>
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight break-words">{company.name}</h1>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              {company.industry && <Badge variant="secondary">{t(`companies.industries.${company.industry}`)}</Badge>}
              {company.city && <span>{company.city}</span>}
            </div>
          </div>
        </div>
        {!editing && (
          <div className="flex shrink-0 gap-2">
            {canEdit && (
              <Button variant="outline" onClick={() => setEditing(true)}>
                <Pencil className="size-4" />
                {t('common.edit')}
              </Button>
            )}
            {canDelete && (
              <Button variant="destructive" onClick={() => void askDelete()} disabled={remove.isPending}>
                <Trash2 className="size-4" />
                {t('common.delete')}
              </Button>
            )}
          </div>
        )}
      </div>

      {editing ? (
        <Card>
          <CardHeader>
            <CardTitle>{t('companies.edit')}</CardTitle>
          </CardHeader>
          <CardContent>
            <CompanyForm company={company} onSaved={saved} onCancel={() => setEditing(false)} />
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          <div className="flex flex-wrap gap-2">
            <ContactButtons phone={company.phone} email={company.email} className="contents" />
            {company.website && (
              <Button
                variant="outline"
                size="sm"
                nativeButton={false}
                render={<a href={company.website} target="_blank" rel="noreferrer noopener" />}
              >
                <Globe className="size-3.5" />
                {t('companies.visitWebsite')}
              </Button>
            )}
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{t('companies.details')}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-5 sm:grid-cols-2">
              <Detail icon={Phone} label={t('common.phone')}>
                <span className="font-latin" dir="ltr">
                  {company.phone || '—'}
                </span>
              </Detail>
              <Detail icon={Mail} label={t('common.email')}>
                <span className="font-latin">{company.email || '—'}</span>
              </Detail>
              <Detail icon={Globe} label={t('companies.website')}>
                <span className="font-latin" dir="ltr">
                  {company.website || '—'}
                </span>
              </Detail>
              <Detail icon={MapPin} label={t('companies.address')}>
                {[company.address, company.city].filter(Boolean).join(', ') || '—'}
              </Detail>
              <Detail icon={UserRound} label={t('companies.assignedTo')}>
                {company.assigned_to_name ?? t('companies.unassigned')}
              </Detail>
            </CardContent>
          </Card>

          <CompanyContacts companyId={company.id} />

          <Card>
            <CardHeader>
              <CardTitle>{t('companies.notes')}</CardTitle>
            </CardHeader>
            <CardContent>
              {company.notes ? (
                <p className="text-sm whitespace-pre-wrap">{company.notes}</p>
              ) : (
                <p className="text-sm text-muted-foreground">{t('companies.noNotes')}</p>
              )}
            </CardContent>
          </Card>

          <Timeline target={{ company: company.id }} />

          <p className="text-xs text-muted-foreground">
            {/* <bdi> keeps names in place when Latin names sit inside Urdu sentences */}
            <bdi>
              <Trans
                i18nKey="companies.createdBy"
                values={{ name: company.created_by_name ?? t('admin.audit.system'), when: fmt.dateTime(company.created_at) }}
                components={{ b: <bdi className="whitespace-nowrap" /> }}
              />
            </bdi>
            {' · '}
            <bdi>
              <Trans
                i18nKey="companies.updatedBy"
                values={{ name: company.updated_by_name ?? t('admin.audit.system'), when: fmt.relative(company.updated_at) }}
                components={{ b: <bdi className="whitespace-nowrap" /> }}
              />
            </bdi>
          </p>
        </div>
      )}
    </div>
  )
}
