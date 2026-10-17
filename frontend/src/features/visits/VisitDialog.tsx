import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Building2, CheckSquare, LocateFixed, MapPin, Store, UserRound, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { FormDialog, FormField, SimpleSelect } from '@/components/common'
import { RecordPicker, type Picked } from '@/components/common/RecordPicker'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { VendorSelect } from '@/features/vendors/VendorDialog'
import { api, apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { officeMoment, officeParts, todayInOffice } from '@/lib/bookings'
import { useFormat } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useVendorOptions } from '@/lib/vendors'
import { useVisitPeople, VISIT_PURPOSES, VISITS_KEY, type Visit, type VisitPurpose } from '@/lib/visits'

/** What a "Plan visit" button already knows: the record, its address, the task it carries out. */
export interface VisitPrefill {
  target?: Picked
  title?: string
  address?: string
  city?: string
  task?: { id: number; title: string }
}

type Where = 'client' | 'vendor' | 'place'

export function VisitDialog({ visit, prefill, onClose }: { visit?: Visit; prefill?: VisitPrefill; onClose: () => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const me = useMe()
  const tz = fmt.settings.timezone
  const queryClient = useQueryClient()
  const { data: people } = useVisitPeople()
  const { data: vendors } = useVendorOptions()
  const initialTarget: Picked | null = visit
    ? visit.contact
      ? { target: { contact: visit.contact.id }, name: visit.contact.name, hint: '', type: 'contact' }
      : visit.company
        ? { target: { company: visit.company.id }, name: visit.company.name, hint: '', type: 'company' }
        : null
    : prefill?.target && prefill.target.type !== 'vendor' ? prefill.target : null
  const initialVendor = visit?.vendor?.id ?? (prefill?.target && 'vendor' in prefill.target.target ? prefill.target.target.vendor : null)
  const [where, setWhere] = useState<Where>(initialVendor ? 'vendor' : initialTarget || !visit ? (visit?.place_name ? 'place' : 'client') : 'place')
  const [client, setClient] = useState<Picked | null>(initialTarget)
  const [vendor, setVendor] = useState<number | null>(initialVendor ?? null)
  const start = visit ? officeParts(tz, visit.start) : null
  const end = visit ? officeParts(tz, visit.end) : null
  const [form, setForm] = useState({
    title: visit?.title ?? prefill?.title ?? '',
    purpose: visit?.purpose ?? ('meeting' as VisitPurpose),
    place_name: visit?.place_name ?? '',
    address: visit?.address ?? prefill?.address ?? '',
    city: visit?.city ?? prefill?.city ?? '',
    date: start?.date ?? todayInOffice(tz),
    from: start?.time ?? '10:00',
    to: end?.time ?? '11:00',
    assigned_to: visit?.assigned_to ?? me.id,
    companions: visit?.companions.map((c) => c.id) ?? ([] as number[]),
    latitude: visit?.latitude ?? '',
    longitude: visit?.longitude ?? '',
    notes: visit?.notes ?? '',
  })
  const [task, setTask] = useState(visit?.task ?? prefill?.task ?? null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [locating, setLocating] = useState(false)
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }))
  const planFor = people?.plan_for ?? []
  const along = (people?.companions ?? []).filter((p) => p.id !== form.assigned_to)
  const willAsk = !visit && fmt.settings.visits_need_approval && me.role === 'staff' && form.assigned_to === me.id

  const pickVendor = (id: number | null) => {
    setVendor(id)
    const v = (vendors ?? []).find((x) => x.id === id)
    if (v) setForm((f) => ({ ...f, address: f.address || v.address || v.areas, city: f.city || v.city }))
  }
  const locateMe = () => {
    if (!navigator.geolocation) return toast.error(t('visits.noLocation'))
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false)
        setForm((f) => ({ ...f, latitude: pos.coords.latitude.toFixed(6), longitude: pos.coords.longitude.toFixed(6) }))
        toast.success(t('visits.locationSet', { metres: Math.round(pos.coords.accuracy) }))
      },
      () => {
        setLocating(false)
        toast.error(t('visits.noLocation'))
      },
      { enableHighAccuracy: true, timeout: 15_000 },
    )
  }
  const save = useMutation({
    mutationFn: async () => {
      const target =
        where === 'client' && client
          ? 'contact' in client.target ? { contact: client.target.contact, company: null } : 'company' in client.target ? { company: client.target.company, contact: null } : {}
          : { contact: null, company: null }
      const body = {
        title: form.title, purpose: form.purpose, notes: form.notes, address: form.address, city: form.city,
        ...target, vendor: where === 'vendor' ? vendor : null, place_name: where === 'place' ? form.place_name : '',
        start: officeMoment(tz, form.date, form.from), end: officeMoment(tz, form.date, form.to),
        assigned_to: form.assigned_to, companions: form.companions.filter((c) => c !== form.assigned_to),
        latitude: form.latitude || null, longitude: form.longitude || null, task: task?.id ?? null,
      }
      return visit ? api.patch(`/visits/${visit.id}/`, body) : api.post('/visits/', body)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: VISITS_KEY })
      void queryClient.invalidateQueries({ queryKey: ['timeline'] })
      void queryClient.invalidateQueries({ queryKey: ['calendar'] })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      toast.success(t(visit ? 'common.saved' : willAsk ? 'visits.requestedToast' : 'visits.plannedToast'))
      onClose()
    },
    onError: (e) => {
      const err = apiError(e)
      setErrors(err.fields)
      toast.error(Object.values(err.fields)[0] ?? err.message)
    },
  })
  const ready = form.title.trim() && form.date && form.from && form.to &&
    ((where === 'client' && client) || (where === 'vendor' && vendor) || (where === 'place' && form.place_name.trim()))
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={visit ? t('visits.editTitle') : t('visits.plan')}
      description={willAsk ? t('visits.approvalHint') : undefined}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !ready}>{t(visit ? 'common.save' : willAsk ? 'visits.send' : 'visits.plan')}</Button>
        </>
      }
    >
      <div className="grid gap-4">
        <div className="grid gap-3 sm:grid-cols-[1fr_12rem]">
          <FormField id="vs-title" label={t('visits.what')} error={errors.title}>
            <Input id="vs-title" value={form.title} dir="auto" maxLength={150} onChange={(e) => set('title', e.target.value)} placeholder={t('visits.whatPlaceholder')} />
          </FormField>
          <FormField id="vs-purpose" label={t('visits.purpose')}>
            <SimpleSelect id="vs-purpose" value={form.purpose} onChange={(v) => set('purpose', v as VisitPurpose)} options={VISIT_PURPOSES.map((p) => ({ value: p, label: t(`visits.purposes.${p}`) }))} />
          </FormField>
        </div>
        <div className="grid gap-2">
          <span className="text-sm font-medium">{t('visits.whoOrWhere')}</span>
          <div className="grid grid-cols-3 gap-1.5" role="radiogroup" aria-label={t('visits.whoOrWhere')}>
            {(['client', 'vendor', 'place'] as const).map((w) => (
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
            <RecordPicker idPrefix="visit-target" onPick={setClient} />
          ))}
          {where === 'vendor' && (
            <div className="flex items-center gap-2">
              <Store className="size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1"><VendorSelect id="vs-vendor" value={vendor} onChange={pickVendor} noneLabel={t('visits.chooseVendor')} /></div>
            </div>
          )}
          {where === 'place' && (
            <Input value={form.place_name} dir="auto" maxLength={150} onChange={(e) => set('place_name', e.target.value)} placeholder={t('visits.placePlaceholder')} aria-label={t('visits.where.place')} />
          )}
          {errors.contact && <p className="text-xs text-destructive">{errors.contact}</p>}
          {errors.place_name && <p className="text-xs text-destructive">{errors.place_name}</p>}
        </div>
        <div className="grid gap-3 sm:grid-cols-[1fr_10rem]">
          <FormField id="vs-address" label={t('visits.address')}>
            <Input id="vs-address" value={form.address} dir="auto" maxLength={255} onChange={(e) => set('address', e.target.value)} />
          </FormField>
          <FormField id="vs-city" label={t('visits.city')}>
            <Input id="vs-city" value={form.city} dir="auto" maxLength={100} onChange={(e) => set('city', e.target.value)} />
          </FormField>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <FormField id="vs-date" label={t('visits.date')} error={errors.start}>
            <Input id="vs-date" type="date" value={form.date} onChange={(e) => e.target.value && set('date', e.target.value)} className="font-latin" />
          </FormField>
          <FormField id="vs-from" label={t('visits.from')}>
            <Input id="vs-from" type="time" step={900} value={form.from} onChange={(e) => set('from', e.target.value)} className="font-latin" />
          </FormField>
          <FormField id="vs-to" label={t('visits.to')} error={errors.end}>
            <Input id="vs-to" type="time" step={900} value={form.to} onChange={(e) => set('to', e.target.value)} className="font-latin" />
          </FormField>
        </div>
        {planFor.length > 1 && (
          <FormField id="vs-person" label={t('visits.who')} error={errors.assigned_to}>
            <SimpleSelect id="vs-person" value={String(form.assigned_to)} onChange={(v) => set('assigned_to', Number(v))} options={planFor.map((p) => ({ value: String(p.id), label: p.name }))} />
          </FormField>
        )}
        {along.length > 0 && (
          <div className="grid gap-1.5">
            <span className="text-sm font-medium">{t('visits.companions')}</span>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('visits.companions')}>
              {along.map((p) => {
                const on = form.companions.includes(p.id)
                return (
                  <button key={p.id} type="button" aria-pressed={on}
                    onClick={() => set('companions', on ? form.companions.filter((x) => x !== p.id) : [...form.companions, p.id])}
                    className={cn('rounded-full border px-3 py-1 text-xs', on ? 'border-primary bg-primary text-primary-foreground' : 'hover:bg-muted')}>
                    <bdi>{p.name}</bdi>
                  </button>
                )
              })}
            </div>
            {errors.companions && <p className="text-xs text-destructive">{errors.companions}</p>}
          </div>
        )}
        <div className="grid gap-1.5">
          <span className="flex items-center gap-1.5 text-sm font-medium"><MapPin className="size-4 text-muted-foreground" />{t('visits.pin')}</span>
          <div className="flex flex-wrap items-center gap-2">
            <Input value={form.latitude} dir="ltr" inputMode="decimal" onChange={(e) => set('latitude', e.target.value)} placeholder={t('visits.latitude')} aria-label={t('visits.latitude')} className="w-36 font-latin" />
            <Input value={form.longitude} dir="ltr" inputMode="decimal" onChange={(e) => set('longitude', e.target.value)} placeholder={t('visits.longitude')} aria-label={t('visits.longitude')} className="w-36 font-latin" />
            <Button type="button" variant="outline" size="sm" onClick={locateMe} disabled={locating}>
              <LocateFixed className="size-4" />
              {t('visits.useMyLocation')}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">{errors.latitude ?? t('visits.pinHint')}</p>
        </div>
        {task && (
          <div className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
            <CheckSquare className="size-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate">{t('visits.forTask')} <bdi className="font-medium">{task.title}</bdi></span>
            <Button variant="ghost" size="icon-xs" onClick={() => setTask(null)} aria-label={t('visits.unlinkTask')}><X className="size-3.5" /></Button>
          </div>
        )}
        <FormField id="vs-notes" label={t('visits.notes')}>
          <Textarea id="vs-notes" value={form.notes} dir="auto" maxLength={4000} onChange={(e) => set('notes', e.target.value)} className="min-h-16" />
        </FormField>
      </div>
    </FormDialog>
  )
}
