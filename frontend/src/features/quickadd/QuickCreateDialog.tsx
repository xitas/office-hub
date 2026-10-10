import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { FormDialog } from '@/components/common'
import { CreatedPanel } from '@/components/common/CreatedPanel'
import { CompanyForm } from '@/features/companies/CompanyForm'
import { ContactForm } from '@/features/contacts/ContactForm'

type Kind = 'contact' | 'company'
interface Created {
  id: number
  name: string
}

/** Quick add → Contact / Company, without leaving the current page. */
export function QuickCreateDialog({ kind, open, onOpenChange }: { kind: Kind; open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [created, setCreated] = useState<Created | null>(null)
  // A fresh form for every "Add another".
  const [round, setRound] = useState(0)

  const close = () => {
    onOpenChange(false)
    setCreated(null)
  }
  const saved = (record: Created) => {
    void queryClient.invalidateQueries({ queryKey: [kind === 'contact' ? 'contacts' : 'companies'] })
    void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    setCreated(record)
  }
  const path = kind === 'contact' ? '/contacts' : '/companies'

  return (
    <FormDialog
      open={open}
      onOpenChange={(o) => (o ? onOpenChange(true) : close())}
      title={t(kind === 'contact' ? 'contacts.add' : 'companies.add')}
    >
      {created ? (
        <CreatedPanel
          message={t(kind === 'contact' ? 'quickAdd.contactAdded' : 'quickAdd.companyAdded', { name: created.name })}
          onOpen={() => {
            close()
            navigate(`${path}/${created.id}`)
          }}
          onAnother={() => {
            setCreated(null)
            setRound((r) => r + 1)
          }}
          onClose={close}
        />
      ) : kind === 'contact' ? (
        <ContactForm key={round} onCancel={close} onSaved={(c) => saved({ id: c.id, name: c.full_name })} />
      ) : (
        <CompanyForm key={round} onCancel={close} onSaved={(c) => saved({ id: c.id, name: c.name })} />
      )}
    </FormDialog>
  )
}
