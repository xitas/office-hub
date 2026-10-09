import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { FormDialog, PageHeader } from '@/components/common'
import { Button } from '@/components/ui/button'
import { EMPTY_CONTACT_FILTERS, filterParams, type ContactFilters } from '@/lib/contacts'
import { usePermission } from '@/lib/permissions'
import { useDebouncedValue } from '@/lib/utils'
import { TransferButtons } from '@/features/transfer/TransferButtons'
import { ContactFilterBar, ContactResults } from './ContactBrowser'
import { ContactForm } from './ContactForm'

export function ContactsPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const canCreate = usePermission('contacts.create')

  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<ContactFilters>(() => ({
    ...EMPTY_CONTACT_FILTERS,
    // "View all" from a company page links here with ?company=ID
    company: params.get('new') !== '1' && params.get('company') ? String(params.get('company')) : EMPTY_CONTACT_FILTERS.company,
  }))
  const [page, setPage] = useState(1)
  const q = useDebouncedValue(search.trim())
  // Quick-add opens the form via ?new=1 (optionally &company=ID to pre-fill it).
  const creating = params.get('new') === '1'
  const presetCompany = creating ? Number(params.get('company')) || null : null
  const closeCreate = () => setParams({}, { replace: true })

  return (
    <>
      <PageHeader
        title={t('contacts.title')}
        subtitle={t('contacts.subtitle')}
        actions={
          <>
            <TransferButtons kind="contacts" params={{ search: q || undefined, ...filterParams(filters) }} />
            {canCreate && (
              <Button onClick={() => setParams({ new: '1' })}>
                <Plus className="size-4" />
                {t('contacts.add')}
              </Button>
            )}
          </>
        }
      />
      <ContactFilterBar
        search={search}
        onSearch={(v) => {
          setSearch(v)
          setPage(1)
        }}
        filters={filters}
        onFilters={(f) => {
          setFilters(f)
          setPage(1)
        }}
      />
      <ContactResults search={q} filters={filters} page={page} onPage={setPage} emptyHint={canCreate ? t('contacts.emptyHint') : undefined} />

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
