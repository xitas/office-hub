import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Building, Mail, MapPin, MessageCircle, Pencil, Phone, Tag as TagIcon, Trash2, UserRound } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, SimpleSelect, UserAvatar } from '@/components/common'
import { ContactButtons } from '@/components/common/ContactButtons'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { api, apiError } from '@/lib/api'
import { useConfirm } from '@/lib/confirm'
import { CONTACT_STATUSES } from '@/lib/contacts'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import type { Contact, ContactStatus } from '@/lib/types'
import { Timeline } from '@/features/timeline/Timeline'
import { ContactForm } from './ContactForm'
import { useStatusChange } from './useStatusChange'

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

export function ContactDetailPage() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const confirm = useConfirm()
  const canEdit = usePermission('contacts.edit')
  const canDelete = usePermission('contacts.delete')
  const [editing, setEditing] = useState(false)
  const key = ['contacts', 'detail', id]

  const { data: contact, isLoading, isError, error, refetch } = useQuery({
    queryKey: key,
    queryFn: async () => (await api.get<Contact>(`/contacts/${id}/`)).data,
    retry: false,
  })

  const refreshLists = () => {
    void queryClient.invalidateQueries({ queryKey: ['contacts', 'list'] })
    void queryClient.invalidateQueries({ queryKey: ['contacts', 'facets'] })
    void queryClient.invalidateQueries({ queryKey: ['companies', 'contacts'] })
  }

  // Same flow as the pipeline board (asks for an optional reason when moving to Won/Lost).
  const statusChange = useStatusChange({
    onSuccess: (updated) => {
      queryClient.setQueryData(key, updated)
      refreshLists()
      void queryClient.invalidateQueries({ queryKey: ['contacts', 'pipeline'] })
      void queryClient.invalidateQueries({ queryKey: ['timeline'] })
    },
  })

  const remove = useMutation({
    mutationFn: () => api.delete(`/contacts/${id}/`),
    onSuccess: () => {
      refreshLists()
      toast.success(t('common.deleted'))
      navigate('/contacts')
    },
    onError: (err) => toast.error(apiError(err).message),
  })

  const back = (
    <Button variant="ghost" size="sm" className="-ms-2 mb-3" nativeButton={false} render={<Link to="/contacts" />}>
      <ArrowLeft className="size-4 rtl:rotate-180" />
      {t('contacts.back')}
    </Button>
  )

  if (isLoading) return <Skeleton className="h-96 max-w-3xl rounded-xl" />
  if (isError || !contact) {
    const notFound = (error as { response?: { status?: number } } | null)?.response?.status === 404
    return (
      <>
        {back}
        {notFound ? (
          <EmptyState icon={UserRound} title={t('contacts.notFound')} hint={t('contacts.notFoundHint')} />
        ) : (
          <ErrorState onRetry={() => void refetch()} />
        )}
      </>
    )
  }

  const askDelete = async () => {
    const ok = await confirm({
      title: t('contacts.deleteTitle', { name: contact.full_name }),
      description: t('contacts.deleteHint'),
      confirmLabel: t('common.delete'),
      destructive: true,
    })
    if (ok) remove.mutate()
  }

  return (
    <div className="max-w-3xl">
      {statusChange.dialog}
      {back}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <UserAvatar name={contact.full_name} className="size-12 text-base" />
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight break-words">{contact.full_name}</h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {contact.job_title}
              {contact.job_title && contact.company_name && ' · '}
              {contact.company && (
                <Link to={`/companies/${contact.company}`} className="text-primary hover:underline">
                  {contact.company_name}
                </Link>
              )}
            </p>
            <div className="mt-2">
              <StatusBadge status={contact.status} />
            </div>
          </div>
        </div>
        {!editing && (
          <div className="flex shrink-0 flex-wrap gap-2">
            {canEdit && (
              <SimpleSelect
                className="w-auto min-w-40"
                value={contact.status}
                disabled={statusChange.pending === contact.id}
                onChange={(v) => statusChange.requestChange(contact, v as ContactStatus)}
                options={CONTACT_STATUSES.map((s) => ({ value: s, label: t(`contacts.statuses.${s}`) }))}
              />
            )}
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
            <CardTitle>{t('contacts.edit')}</CardTitle>
          </CardHeader>
          <CardContent>
            <ContactForm
              contact={contact}
              onCancel={() => setEditing(false)}
              onSaved={(updated) => {
                queryClient.setQueryData(key, updated)
                refreshLists()
                setEditing(false)
              }}
            />
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          <ContactButtons phone={contact.phone} whatsapp={contact.whatsapp} email={contact.email} />

          <Card>
            <CardHeader>
              <CardTitle>{t('companies.details')}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-5 sm:grid-cols-2">
              <Detail icon={Phone} label={t('common.phone')}>
                <span className="font-latin" dir="ltr">
                  {contact.phone || '—'}
                </span>
              </Detail>
              <Detail icon={MessageCircle} label={t('contacts.whatsapp')}>
                <span className="font-latin" dir="ltr">
                  {contact.whatsapp || (contact.phone ? t('contacts.sameAsPhone') : '—')}
                </span>
              </Detail>
              <Detail icon={Mail} label={t('common.email')}>
                <span className="font-latin">{contact.email || '—'}</span>
              </Detail>
              <Detail icon={Building} label={t('contacts.company')}>
                {contact.company ? (
                  <Link to={`/companies/${contact.company}`} className="text-primary hover:underline">
                    {contact.company_name}
                  </Link>
                ) : (
                  '—'
                )}
              </Detail>
              <Detail icon={MapPin} label={t('companies.address')}>
                {[contact.address, contact.city].filter(Boolean).join(', ') || '—'}
              </Detail>
              <Detail icon={UserRound} label={t('companies.assignedTo')}>
                {contact.assigned_to_name ?? t('companies.unassigned')}
              </Detail>
              <div className="sm:col-span-2">
                <Detail icon={TagIcon} label={t('contacts.tags')}>
                  {contact.tags.length ? (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {contact.tags.map((tag) => (
                        <Badge key={tag} variant="secondary" className="font-normal">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <span className="text-muted-foreground">{t('contacts.noTags')}</span>
                  )}
                </Detail>
              </div>
            </CardContent>
          </Card>

          <Timeline target={{ contact: contact.id }} />

          <p className="text-xs text-muted-foreground">
            {/* <bdi> keeps names in place when Latin names sit inside Urdu sentences */}
            <bdi>
              <Trans
                i18nKey="companies.createdBy"
                values={{ name: contact.created_by_name ?? t('admin.audit.system'), when: fmt.dateTime(contact.created_at) }}
                components={{ b: <bdi className="whitespace-nowrap" /> }}
              />
            </bdi>
            {' · '}
            <bdi>
              <Trans
                i18nKey="companies.updatedBy"
                values={{ name: contact.updated_by_name ?? t('admin.audit.system'), when: fmt.relative(contact.updated_at) }}
                components={{ b: <bdi className="whitespace-nowrap" /> }}
              />
            </bdi>
          </p>
        </div>
      )}
    </div>
  )
}
