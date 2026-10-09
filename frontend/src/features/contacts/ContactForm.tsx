import { useQuery } from '@tanstack/react-query'
import { Loader2, TriangleAlert } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { FormField, SimpleSelect, TextField } from '@/components/common'
import { TagInput } from '@/components/common/TagInput'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { api, apiError } from '@/lib/api'
import { useAssignableUsers } from '@/lib/companies'
import { CONTACT_STATUSES, useCompanyOptions } from '@/lib/contacts'
import type { Contact, ContactStatus, DuplicateMatch } from '@/lib/types'
import { useDebouncedValue } from '@/lib/utils'

interface ContactInput {
  first_name: string
  last_name: string
  company: number | null
  job_title: string
  phone: string
  whatsapp: string
  email: string
  address: string
  city: string
  tags: string[]
  status: ContactStatus
  assigned_to: number | null
}

function initial(contact?: Contact, companyId?: number | null): ContactInput {
  return {
    first_name: contact?.first_name ?? '',
    last_name: contact?.last_name ?? '',
    company: contact ? contact.company : (companyId ?? null),
    job_title: contact?.job_title ?? '',
    phone: contact?.phone ?? '',
    whatsapp: contact?.whatsapp ?? '',
    email: contact?.email ?? '',
    address: contact?.address ?? '',
    city: contact?.city ?? '',
    tags: contact?.tags ?? [],
    status: contact?.status ?? 'new',
    assigned_to: contact?.assigned_to ?? null,
  }
}

/** Live duplicate check (warning only): another contact with the same phone/WhatsApp or email. */
function useDuplicates(form: ContactInput, excludeId?: number) {
  // Debounce a string (a fresh object each render would never settle).
  const raw = useDebouncedValue(JSON.stringify([form.phone.trim(), form.whatsapp.trim(), form.email.trim()]), 500)
  const [phone, whatsapp, email] = JSON.parse(raw) as [string, string, string]
  const key = { phone, whatsapp, email }
  const hasInput = key.email.includes('@') || key.phone.replace(/\D/g, '').length >= 7 || key.whatsapp.replace(/\D/g, '').length >= 7
  return useQuery({
    queryKey: ['contacts', 'duplicates', key, excludeId],
    queryFn: async () =>
      (
        await api.get<{ duplicates: DuplicateMatch[] }>('/contacts/duplicates/', {
          params: { ...key, exclude: excludeId },
        })
      ).data.duplicates,
    enabled: hasInput,
    staleTime: 10_000,
  }).data
}

export function ContactForm({
  contact,
  companyId,
  onSaved,
  onCancel,
}: {
  contact?: Contact
  /** Pre-selected company for a new contact (e.g. "Add contact" on a company page). */
  companyId?: number | null
  onSaved: (contact: Contact) => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  const assignable = useAssignableUsers()
  const { data: companies } = useCompanyOptions()
  const [form, setForm] = useState<ContactInput>(() => initial(contact, companyId))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const duplicates = useDuplicates(form, contact?.id) ?? []

  const set = <K extends keyof ContactInput>(key: K) => (value: ContactInput[K]) => setForm((f) => ({ ...f, [key]: value }))
  const text = (key: keyof ContactInput) => (e: { target: { value: string } }) => set(key)(e.target.value as never)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErrors({})
    const payload: Partial<ContactInput> = { ...form }
    if (assignable === null) delete payload.assigned_to // staff: the server assigns to themselves
    try {
      const { data } = contact
        ? await api.patch<Contact>(`/contacts/${contact.id}/`, payload)
        : await api.post<Contact>('/contacts/', payload)
      toast.success(contact ? t('common.saved') : t('common.created'))
      onSaved(data)
    } catch (err) {
      const info = apiError(err)
      setErrors(info.fields)
      if (!Object.keys(info.fields).length) toast.error(info.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="grid gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField id="ct-first" label={t('contacts.firstName')} value={form.first_name} onChange={text('first_name')} error={errors.first_name} required />
        <TextField id="ct-last" label={t('contacts.lastName')} value={form.last_name} onChange={text('last_name')} error={errors.last_name} />
        <FormField id="ct-company" label={t('contacts.company')} error={errors.company}>
          <SimpleSelect
            id="ct-company"
            value={form.company ? String(form.company) : 'none'}
            onChange={(v) => set('company')(v === 'none' ? null : Number(v))}
            options={[
              { value: 'none', label: t('contacts.noCompany') },
              ...(companies ?? []).map((c) => ({ value: String(c.id), label: c.name })),
            ]}
          />
        </FormField>
        <TextField id="ct-title" label={t('common.jobTitle')} value={form.job_title} onChange={text('job_title')} error={errors.job_title} />
        <TextField id="ct-phone" label={t('common.phone')} value={form.phone} onChange={text('phone')} error={errors.phone} dir="ltr" inputMode="tel" />
        <TextField
          id="ct-whatsapp"
          label={t('contacts.whatsapp')}
          hint={t('contacts.whatsappHint')}
          value={form.whatsapp}
          onChange={text('whatsapp')}
          error={errors.whatsapp}
          dir="ltr"
          inputMode="tel"
        />
        <TextField id="ct-email" type="email" label={t('common.email')} value={form.email} onChange={text('email')} error={errors.email} dir="ltr" />
        <TextField id="ct-city" label={t('companies.city')} value={form.city} onChange={text('city')} error={errors.city} />
      </div>

      {duplicates.length > 0 && (
        <Alert className="border-warning/50 bg-warning/10">
          <TriangleAlert className="size-4 text-warning" />
          <AlertTitle>{t('contacts.duplicateTitle')}</AlertTitle>
          <AlertDescription>
            <ul className="mt-1 grid gap-1">
              {duplicates.map((d, i) => (
                <li key={d.id ?? `hidden-${i}`}>
                  {/* <bdi> keeps Latin names and Urdu text in the right order in either direction */}
                  <bdi>
                    {d.visible && d.id ? (
                      <Link to={`/contacts/${d.id}`} target="_blank" className="font-medium text-foreground underline underline-offset-2">
                        {d.name}
                      </Link>
                    ) : (
                      <span className="font-medium text-foreground">{t('contacts.duplicateHidden')}</span>
                    )}
                  </bdi>
                  {d.company_name && (
                    <>
                      {' · '}
                      <bdi>{d.company_name}</bdi>
                    </>
                  )}
                  {d.assigned_to_name && (
                    <>
                      {' · '}
                      <bdi>
                        <Trans i18nKey="contacts.duplicateOwner" values={{ name: d.assigned_to_name }} components={{ name: <bdi /> }} />
                      </bdi>
                    </>
                  )}
                  {' · '}
                  <bdi>{d.matched.map((m) => t(`contacts.matched.${m}`)).join(t('contacts.and'))}</bdi>
                </li>
              ))}
            </ul>
            <p className="mt-1 text-xs">{t('contacts.duplicateHint')}</p>
          </AlertDescription>
        </Alert>
      )}

      <TextField id="ct-address" label={t('companies.address')} value={form.address} onChange={text('address')} error={errors.address} />
      <FormField id="ct-tags" label={t('contacts.tags')} error={errors.tags} hint={t('contacts.tagsHint')}>
        <TagInput id="ct-tags" value={form.tags} onChange={set('tags')} />
      </FormField>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField id="ct-status" label={t('contacts.status')} error={errors.status}>
          <SimpleSelect
            id="ct-status"
            value={form.status}
            onChange={(v) => set('status')(v as ContactStatus)}
            options={CONTACT_STATUSES.map((s) => ({ value: s, label: t(`contacts.statuses.${s}`) }))}
          />
        </FormField>
        {assignable !== null && (
          <FormField id="ct-assigned" label={t('companies.assignedTo')} error={errors.assigned_to}>
            <SimpleSelect
              id="ct-assigned"
              value={form.assigned_to ? String(form.assigned_to) : 'none'}
              onChange={(v) => set('assigned_to')(v === 'none' ? null : Number(v))}
              options={[
                { value: 'none', label: t('companies.unassigned') },
                ...assignable.map((u) => ({ value: String(u.id), label: u.full_name })),
              ]}
            />
          </FormField>
        )}
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
        <Button type="submit" disabled={busy}>
          {busy && <Loader2 className="size-4 animate-spin" />}
          {contact ? t('common.save') : t('common.create')}
        </Button>
      </div>
    </form>
  )
}
