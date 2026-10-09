import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Phone, Plus, UsersRound } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { EmptyState, FormDialog, UserAvatar } from '@/components/common'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { usePermission } from '@/lib/permissions'
import type { Contact, Paginated } from '@/lib/types'
import { ContactForm } from './ContactForm'

const LIMIT = 50

/** The contacts of one company (those this user can see), with "Add contact" pre-filling the company. */
export function CompanyContacts({ companyId }: { companyId: number }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const canCreate = usePermission('contacts.create')
  const [adding, setAdding] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['companies', 'contacts', companyId],
    queryFn: async () =>
      (await api.get<Paginated<Contact>>('/contacts/', { params: { company: companyId, page_size: LIMIT } })).data,
  })

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle>
          {t('contacts.title')}
          {data && data.count > 0 && <span className="ms-1.5 text-sm font-normal text-muted-foreground font-latin">({data.count})</span>}
        </CardTitle>
        {canCreate && (
          <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
            <Plus className="size-4" />
            {t('contacts.add')}
          </Button>
        )}
      </CardHeader>
      <CardContent className="px-0">
        {isLoading ? (
          <div className="space-y-2 px-4">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : !data?.results.length ? (
          <EmptyState icon={UsersRound} title={t('contacts.noneForCompany')} className="py-4" />
        ) : (
          <ul className="divide-y">
            {data.results.map((c) => (
              <li key={c.id}>
                <Link to={`/contacts/${c.id}`} className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-muted/50">
                  <UserAvatar name={c.full_name} className="size-8" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{c.full_name}</p>
                    <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                      {c.job_title && <span>{c.job_title}</span>}
                      {c.phone && (
                        <span className="flex items-center gap-1 font-latin" dir="ltr">
                          <Phone className="size-3" />
                          {c.phone}
                        </span>
                      )}
                    </p>
                  </div>
                  <StatusBadge status={c.status} className="shrink-0" />
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground rtl:rotate-180" />
                </Link>
              </li>
            ))}
          </ul>
        )}
        {data && data.count > LIMIT && (
          <div className="px-4 pt-2">
            <Button variant="link" size="sm" className="px-0" nativeButton={false} render={<Link to={`/contacts?company=${companyId}`} />}>
              {t('contacts.viewAll', { count: data.count })}
            </Button>
          </div>
        )}
      </CardContent>

      {adding && (
        <FormDialog open onOpenChange={(o) => !o && setAdding(false)} title={t('contacts.add')}>
          <ContactForm
            companyId={companyId}
            onCancel={() => setAdding(false)}
            onSaved={() => {
              void queryClient.invalidateQueries({ queryKey: ['companies', 'contacts', companyId] })
              void queryClient.invalidateQueries({ queryKey: ['contacts'] })
              setAdding(false)
            }}
          />
        </FormDialog>
      )}
    </Card>
  )
}
