import { Loader2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { FormField, SimpleSelect, TextField } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { EMPTY_COMPANY, INDUSTRIES, useAssignableUsers, type CompanyInput } from '@/lib/companies'
import type { Company } from '@/lib/types'

/** Create (no `company`) or edit form. Calls onSaved with the saved company. */
export function CompanyForm({
  company,
  onSaved,
  onCancel,
}: {
  company?: Company
  onSaved: (company: Company) => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  const assignable = useAssignableUsers()
  const [form, setForm] = useState<CompanyInput>(() =>
    company
      ? {
          name: company.name,
          industry: company.industry,
          phone: company.phone,
          email: company.email,
          website: company.website,
          address: company.address,
          city: company.city,
          notes: company.notes,
          assigned_to: company.assigned_to,
        }
      : EMPTY_COMPANY,
  )
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const set = <K extends keyof CompanyInput>(key: K) => (value: CompanyInput[K]) => setForm((f) => ({ ...f, [key]: value }))
  const text = (key: keyof CompanyInput) => (e: { target: { value: string } }) => set(key)(e.target.value as never)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErrors({})
    const payload: Partial<CompanyInput> = { ...form }
    if (assignable === null) delete payload.assigned_to // staff: the server assigns to themselves
    try {
      const { data } = company
        ? await api.patch<Company>(`/companies/${company.id}/`, payload)
        : await api.post<Company>('/companies/', payload)
      toast.success(company ? t('common.saved') : t('common.created'))
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
      <TextField id="c-name" label={t('companies.name')} value={form.name} onChange={text('name')} error={errors.name} required />
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField id="c-industry" label={t('companies.industry')} error={errors.industry}>
          <SimpleSelect
            id="c-industry"
            value={form.industry || 'none'}
            onChange={(v) => set('industry')(v === 'none' ? '' : v)}
            options={[
              { value: 'none', label: t('companies.noIndustry') },
              ...INDUSTRIES.map((i) => ({ value: i, label: t(`companies.industries.${i}`) })),
            ]}
          />
        </FormField>
        <TextField id="c-city" label={t('companies.city')} value={form.city} onChange={text('city')} error={errors.city} />
        <TextField
          id="c-phone"
          label={t('common.phone')}
          value={form.phone}
          onChange={text('phone')}
          error={errors.phone}
          dir="ltr"
          inputMode="tel"
        />
        <TextField
          id="c-email"
          type="email"
          label={t('common.email')}
          value={form.email}
          onChange={text('email')}
          error={errors.email}
          dir="ltr"
        />
        <TextField
          id="c-website"
          label={t('companies.website')}
          value={form.website}
          onChange={text('website')}
          error={errors.website}
          dir="ltr"
          placeholder="example.com"
        />
        {assignable !== null && (
          <FormField id="c-assigned" label={t('companies.assignedTo')} error={errors.assigned_to}>
            <SimpleSelect
              id="c-assigned"
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
      <TextField id="c-address" label={t('companies.address')} value={form.address} onChange={text('address')} error={errors.address} />
      <FormField id="c-notes" label={t('companies.notes')} error={errors.notes}>
        <Textarea id="c-notes" value={form.notes} onChange={text('notes')} rows={4} />
      </FormField>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
        <Button type="submit" disabled={busy}>
          {busy && <Loader2 className="size-4 animate-spin" />}
          {company ? t('common.save') : t('common.create')}
        </Button>
      </div>
    </form>
  )
}
