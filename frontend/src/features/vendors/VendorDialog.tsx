import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Star } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { FormDialog, FormField, SimpleSelect } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { usePermission } from '@/lib/permissions'
import { cn } from '@/lib/utils'
import { categoryName, useVendorCategories, useVendorOptions, VENDORS_KEY, type Vendor } from '@/lib/vendors'

/** Add or change a vendor. Anyone can; preferred and active are for managers and admins. */
export function VendorDialog({ vendor, onClose, onSaved }: { vendor?: Vendor; onClose: () => void; onSaved?: (v: Vendor) => void }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const canCurate = usePermission('vendors.delete')
  const { data: categories } = useVendorCategories()
  const [form, setForm] = useState({
    name: vendor?.name ?? '',
    categories: vendor?.categories ?? ([] as number[]),
    contact_person: vendor?.contact_person ?? '',
    phone: vendor?.phone ?? '',
    whatsapp: vendor?.whatsapp ?? '',
    email: vendor?.email ?? '',
    website: vendor?.website ?? '',
    address: vendor?.address ?? '',
    city: vendor?.city ?? '',
    areas: vendor?.areas ?? '',
    payment_terms: vendor?.payment_terms ?? '',
    notes: vendor?.notes ?? '',
    rating: vendor?.rating ?? (null as number | null),
    preferred: vendor?.preferred ?? false,
    is_active: vendor?.is_active ?? true,
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }))
  const save = useMutation({
    mutationFn: async () => {
      const body: Partial<typeof form> = { ...form }
      if (!canCurate) {
        delete body.preferred
        delete body.is_active
      }
      return (vendor ? await api.patch<Vendor>(`/vendors/${vendor.id}/`, body) : await api.post<Vendor>('/vendors/', body)).data
    },
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: VENDORS_KEY })
      toast.success(t(vendor ? 'common.saved' : 'vendors.addedToast'))
      onSaved?.(saved)
      onClose()
    },
    onError: (e) => {
      const err = apiError(e)
      setErrors(err.fields)
      toast.error(Object.values(err.fields)[0] ?? err.message)
    },
  })
  const field = (key: 'contact_person' | 'phone' | 'whatsapp' | 'email' | 'website' | 'address' | 'city' | 'areas' | 'payment_terms', opts: { ltr?: boolean; hint?: string; wide?: boolean; type?: string } = {}) => (
    <FormField id={`vd-${key}`} label={t(`vendors.fields.${key}`)} hint={opts.hint} error={errors[key]} className={opts.wide ? 'sm:col-span-2' : undefined}>
      <Input
        id={`vd-${key}`}
        type={opts.type}
        value={form[key]}
        dir={opts.ltr ? 'ltr' : 'auto'}
        className={opts.ltr ? 'font-latin' : undefined}
        onChange={(e) => set(key, e.target.value)}
      />
    </FormField>
  )
  const active = (categories ?? []).filter((c) => c.is_active || form.categories.includes(c.id))
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={vendor ? t('vendors.editTitle', { name: vendor.name }) : t('vendors.add')}
      description={vendor ? undefined : t('vendors.addHint')}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !form.name.trim()}>{t('common.save')}</Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField id="vd-name" label={t('vendors.fields.name')} error={errors.name} className="sm:col-span-2">
          <Input id="vd-name" value={form.name} dir="auto" maxLength={150} onChange={(e) => set('name', e.target.value)} />
        </FormField>
        <div className="grid gap-1.5 sm:col-span-2">
          <span className="text-sm font-medium">{t('vendors.fields.categories')}</span>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('vendors.fields.categories')}>
            {active.map((c) => {
              const on = form.categories.includes(c.id)
              return (
                <button
                  key={c.id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => set('categories', on ? form.categories.filter((x) => x !== c.id) : [...form.categories, c.id])}
                  className={cn('rounded-full border px-3 py-1 text-xs', on ? 'border-primary bg-primary text-primary-foreground' : 'hover:bg-muted')}
                >
                  {categoryName(c, i18n.language)}
                </button>
              )
            })}
          </div>
        </div>
        {field('contact_person')}
        {field('phone', { ltr: true, type: 'tel' })}
        {field('whatsapp', { ltr: true, type: 'tel', hint: t('vendors.whatsappHint') })}
        {field('email', { ltr: true, type: 'email' })}
        {field('city')}
        {field('areas', { hint: t('vendors.areasHint') })}
        {field('address', { wide: true })}
        {field('website', { ltr: true, type: 'url' })}
        {field('payment_terms', { hint: t('vendors.paymentTermsHint') })}
        <div className="grid gap-1.5">
          <span className="text-sm font-medium">{t('vendors.fields.rating')}</span>
          <RatingInput value={form.rating} onChange={(v) => set('rating', v)} />
        </div>
        <FormField id="vd-notes" label={t('vendors.fields.notes')} className="sm:col-span-2">
          <Textarea id="vd-notes" value={form.notes} dir="auto" maxLength={2000} onChange={(e) => set('notes', e.target.value)} className="min-h-16" />
        </FormField>
        {canCurate && (
          <div className="grid gap-2 sm:col-span-2 sm:grid-cols-2">
            <label className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm">
              {t('vendors.fields.preferred')}
              <Switch checked={form.preferred} onCheckedChange={(v) => set('preferred', v)} />
            </label>
            <label className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm">
              {t('vendors.fields.active')}
              <Switch checked={form.is_active} onCheckedChange={(v) => set('is_active', v)} />
            </label>
          </div>
        )}
      </div>
    </FormDialog>
  )
}

function RatingInput({ value, onChange }: { value: number | null; onChange: (v: number | null) => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex items-center gap-0.5" role="radiogroup" aria-label={t('vendors.fields.rating')}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={value === n}
          aria-label={t('vendors.stars', { count: n })}
          onClick={() => onChange(value === n ? null : n)}
          className="rounded p-1 hover:bg-muted"
        >
          <Star className={cn('size-5', value !== null && n <= value ? 'fill-amber-400 text-amber-400' : 'text-muted-foreground')} />
        </button>
      ))}
    </div>
  )
}

export function Stars({ value }: { value: number | null }) {
  const { t } = useTranslation()
  if (!value) return null
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={t('vendors.stars', { count: value })} title={t('vendors.stars', { count: value })}>
      {[1, 2, 3, 4, 5].map((n) => (
        <Star key={n} className={cn('size-3.5', n <= value ? 'fill-amber-400 text-amber-400' : 'text-muted-foreground/40')} />
      ))}
    </span>
  )
}

/** Pick a vendor (supplier, where to buy, paid to), or none. */
export function VendorSelect({ id, value, onChange, noneLabel }: { id: string; value: number | null; onChange: (v: number | null) => void; noneLabel?: string }) {
  const { t } = useTranslation()
  const { data } = useVendorOptions()
  return (
    <SimpleSelect
      id={id}
      value={value ? String(value) : ''}
      onChange={(v) => onChange(v ? Number(v) : null)}
      options={[{ value: '', label: noneLabel ?? t('vendors.none') }, ...(data ?? []).map((v) => ({ value: String(v.id), label: v.name }))]}
    />
  )
}
