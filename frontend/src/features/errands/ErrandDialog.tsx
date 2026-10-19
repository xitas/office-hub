import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Building2, CheckSquare, MapPin, MapPinned, Store, UserRound, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { FormDialog, FormField, SimpleSelect } from '@/components/common'
import { RecordPicker, type Picked } from '@/components/common/RecordPicker'
import { PinPickerDialog } from '@/components/map/PinPickerDialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { VendorSelect } from '@/features/vendors/VendorDialog'
import { api, apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { officeMoment, officeParts, todayInOffice } from '@/lib/bookings'
import { ERRAND_KINDS, ERRANDS_KEY, type Errand, type ErrandKind } from '@/lib/errands'
import { useFormat } from '@/lib/format'
import { useTaskAssignees } from '@/lib/tasks'
import { cn } from '@/lib/utils'
import { useVendorOptions } from '@/lib/vendors'

/** What an "Errand" button already knows: the record (e.g. the courier company), the task it carries out. */
export interface ErrandPrefill {
  target?: Picked
  title?: string
  kind?: ErrandKind
  address?: string
  city?: string
  task?: { id: number; title: string }
}

type Where = 'client' | 'vendor' | 'place'

/** Ask for an errand (or change one): what, where, by when, who does it (or leave it for someone to take). */
export function ErrandDialog({ errand, prefill, onClose }: { errand?: Errand; prefill?: ErrandPrefill; onClose: () => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const me = useMe()
  const tz = fmt.settings.timezone
  const queryClient = useQueryClient()
  const assignees = useTaskAssignees()
  const { data: vendors } = useVendorOptions()
  const initialTarget: Picked | null = errand
    ? errand.contact
      ? { target: { contact: errand.contact.id }, name: errand.contact.name, hint: '', type: 'contact' }
      : errand.company
        ? { target: { company: errand.company.id }, name: errand.company.name, hint: '', type: 'company' }
        : null
    : prefill?.target && prefill.target.type !== 'vendor' ? prefill.target : null
  const initialVendor = errand?.vendor?.id ?? (prefill?.target && 'vendor' in prefill.target.target ? prefill.target.target.vendor : null)
  const [where, setWhere] = useState<Where>(initialVendor ? 'vendor' : initialTarget ? 'client' : errand ? 'place' : 'vendor')
  const [client, setClient] = useState<Picked | null>(initialTarget)
  const [vendor, setVendor] = useState<number | null>(initialVendor ?? null)
  const due = errand?.due_at ? officeParts(tz, errand.due_at) : null
  const [form, setForm] = useState({
    title: errand?.title ?? prefill?.title ?? '',
    kind: errand?.kind ?? prefill?.kind ?? ('courier' as ErrandKind),
    details: errand?.details ?? '',
    place_name: errand?.place_name ?? '',
    address: errand?.address ?? prefill?.address ?? '',
    city: errand?.city ?? prefill?.city ?? '',
    date: due?.date ?? (errand ? '' : todayInOffice(tz)),
    time: due?.time ?? (errand ? '' : '15:00'),
    runner: errand ? (errand.assigned_to ? String(errand.assigned_to) : '') : String(me.id),
    latitude: errand?.latitude ?? '',
    longitude: errand?.longitude ?? '',
  })
  const [task, setTask] = useState(errand?.task ?? prefill?.task ?? null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [picking, setPicking] = useState(false)
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }))
  const pickVendor = (id: number | null) => {
    setVendor(id)
    const v = (vendors ?? []).find((x) => x.id === id)
    if (v) setForm((f) => ({ ...f, address: f.address || v.address || v.areas, city: f.city || v.city }))
  }
  const save = useMutation({
    mutationFn: async () => {
      const target =
        where === 'client' && client
          ? 'contact' in client.target ? { contact: client.target.contact, company: null } : 'company' in client.target ? { company: client.target.company, contact: null } : {}
          : { contact: null, company: null }
      const body = {
        title: form.title, kind: form.kind, details: form.details, address: form.address, city: form.city,
        ...target, vendor: where === 'vendor' ? vendor : null, place_name: where === 'place' ? form.place_name : '',
        due_at: form.date ? officeMoment(tz, form.date, form.time || '17:00') : null,
        assigned_to: form.runner ? Number(form.runner) : null,
        latitude: form.latitude || null, longitude: form.longitude || null, task: task?.id ?? null,
      }
      return errand ? api.patch(`/errands/${errand.id}/`, body) : api.post('/errands/', body)
    },
    onSuccess: () => {
      for (const key of [ERRANDS_KEY, ['timeline'], ['map'], ['dashboard']]) void queryClient.invalidateQueries({ queryKey: key })
      toast.success(t(errand ? 'common.saved' : form.runner ? 'errands.createdToast' : 'errands.openToast'))
      onClose()
    },
    onError: (e) => {
      const err = apiError(e)
      setErrors(err.fields)
      toast.error(Object.values(err.fields)[0] ?? err.message)
    },
  })
  const ready = form.title.trim() &&
    ((where === 'client' && client) || (where === 'vendor' && vendor) || (where === 'place' && (form.place_name.trim() || form.address.trim())))
  const onTheWay = errand?.status === 'on_the_way'
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={errand ? t('errands.editTitle') : t('errands.new')}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !ready}>{t(errand ? 'common.save' : 'errands.ask')}</Button>
        </>
      }
    >
      <div className="grid gap-4">
        <div className="grid gap-3 sm:grid-cols-[1fr_12rem]">
          <FormField id="er-title" label={t('errands.what')} error={errors.title}>
            <Input id="er-title" value={form.title} dir="auto" maxLength={150} onChange={(e) => set('title', e.target.value)} placeholder={t('errands.whatPlaceholder')} />
          </FormField>
          <FormField id="er-kind" label={t('errands.kind')}>
            <SimpleSelect id="er-kind" value={form.kind} onChange={(v) => set('kind', v as ErrandKind)} options={ERRAND_KINDS.map((k) => ({ value: k, label: t(`errands.kinds.${k}`) }))} />
          </FormField>
        </div>
        <div className="grid gap-2">
          <span className="text-sm font-medium">{t('errands.where')}</span>
          <div className="grid grid-cols-3 gap-1.5" role="radiogroup" aria-label={t('errands.where')}>
            {(['vendor', 'client', 'place'] as const).map((w) => (
              <button key={w} type="button" role="radio" aria-checked={where === w} onClick={() => setWhere(w)}
                className={cn('rounded-md border px-2 py-1.5 text-sm', where === w ? 'border-primary bg-primary text-primary-foreground' : 'hover:bg-muted')}>
                {t(`visits.where.${w}`)}
              </button>
            ))}
          </div>
          {where === 'client' && (client ? (
            <div className="flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-sm">
              {client.type === 'contact' ? <UserRound className="size-4 text-muted-foreground" /> : <Building2 className="size-4 text-muted-foreground" />}
              <bdi className="min-w-0 flex-1 truncate font-medium">{client.name}</bdi>
              <Button variant="ghost" size="icon-xs" onClick={() => setClient(null)} aria-label={t('timeline.change')}><X className="size-3.5" /></Button>
            </div>
          ) : (
            <RecordPicker idPrefix="errand-target" onPick={setClient} />
          ))}
          {where === 'vendor' && (
            <div className="flex items-center gap-2">
              <Store className="size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1"><VendorSelect id="er-vendor" value={vendor} onChange={pickVendor} noneLabel={t('visits.chooseVendor')} /></div>
            </div>
          )}
          {where === 'place' && (
            <Input value={form.place_name} dir="auto" maxLength={150} onChange={(e) => set('place_name', e.target.value)} placeholder={t('errands.placePlaceholder')} aria-label={t('visits.where.place')} />
          )}
          {errors.contact && <p className="text-xs text-destructive">{errors.contact}</p>}
          {errors.place_name && <p className="text-xs text-destructive">{errors.place_name}</p>}
        </div>
        <div className="grid gap-3 sm:grid-cols-[1fr_10rem]">
          <FormField id="er-address" label={t('visits.address')}>
            <Input id="er-address" value={form.address} dir="auto" maxLength={255} onChange={(e) => set('address', e.target.value)} />
          </FormField>
          <FormField id="er-city" label={t('visits.city')}>
            <Input id="er-city" value={form.city} dir="auto" maxLength={100} onChange={(e) => set('city', e.target.value)} />
          </FormField>
        </div>
        <div className="grid gap-1.5">
          <span className="flex items-center gap-1.5 text-sm font-medium"><MapPin className="size-4 text-muted-foreground" />{t('visits.pin')}</span>
          <div className="flex flex-wrap items-center gap-2">
            <span className="min-w-0 flex-1 text-sm">
              {form.latitude ? <bdi dir="ltr" className="font-latin">{form.latitude}, {form.longitude}</bdi> : <span className="text-muted-foreground">{t('errands.pinHint')}</span>}
            </span>
            <Button type="button" variant="outline" size="sm" onClick={() => setPicking(true)}>
              <MapPinned className="size-4" />
              {t(form.latitude ? 'map.changePin' : 'map.setPin')}
            </Button>
          </div>
          {picking && (
            <PinPickerDialog title={t('errands.pinTitle')} latitude={form.latitude || null} longitude={form.longitude || null} onClose={() => setPicking(false)}
              onSave={(lat, lng) => setForm((f) => ({ ...f, latitude: lat ?? '', longitude: lng ?? '' }))} />
          )}
          {errors.latitude && <p className="text-xs text-destructive">{errors.latitude}</p>}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <FormField id="er-date" label={t('errands.dueDate')} error={errors.due_at}>
            <Input id="er-date" type="date" value={form.date} onChange={(e) => set('date', e.target.value)} className="font-latin" />
          </FormField>
          <FormField id="er-time" label={t('errands.dueTime')}>
            <Input id="er-time" type="time" step={900} value={form.time} disabled={!form.date} onChange={(e) => set('time', e.target.value)} className="font-latin" />
          </FormField>
        </div>
        <FormField id="er-runner" label={t('errands.runner')} error={errors.assigned_to} hint={form.runner ? undefined : t('errands.openHint')}>
          <SimpleSelect id="er-runner" value={form.runner} onChange={(v) => set('runner', v)} disabled={onTheWay}
            options={[
              { value: '', label: t('errands.anyone') },
              ...(assignees.length ? assignees : [{ id: me.id, full_name: me.full_name }]).map((u) => ({
                value: String(u.id), label: u.id === me.id ? t('timeline.me', { name: u.full_name }) : u.full_name,
              })),
            ]} />
        </FormField>
        <FormField id="er-details" label={t('errands.details')}>
          <Textarea id="er-details" value={form.details} dir="auto" maxLength={2000} onChange={(e) => set('details', e.target.value)} className="min-h-16"
            placeholder={t('errands.detailsPlaceholder')} />
        </FormField>
        {task && (
          <div className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
            <CheckSquare className="size-4 shrink-0 text-muted-foreground" />
            <span className="text-muted-foreground">{t('visits.forTask')}</span>
            <bdi className="min-w-0 flex-1 truncate">{task.title}</bdi>
            <Button variant="ghost" size="icon-xs" onClick={() => setTask(null)} aria-label={t('visits.unlinkTask')}><X className="size-3.5" /></Button>
          </div>
        )}
      </div>
    </FormDialog>
  )
}
