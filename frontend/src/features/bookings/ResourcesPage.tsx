import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Car, DoorOpen, ImageOff, MapPin, Package, Pencil, Plus, Presentation, ShieldCheck, Users } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, FormDialog, FormField, PageHeader, SimpleSelect } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { RESOURCES_KEY, RESOURCE_TYPES, useResources, type Resource, type ResourceType } from '@/lib/bookings'
import { usePermission } from '@/lib/permissions'
import { useDepartments } from '@/lib/queries'
import { useAuthedBlobUrl } from '@/lib/useAuthedBlob'
import { cn } from '@/lib/utils'

const ICONS: Record<ResourceType, typeof DoorOpen> = { room: DoorOpen, projector: Presentation, vehicle: Car, other: Package }

/** Rooms, projectors, vehicles…: what can be booked, by whom. Admins add and change them. */
export function ResourcesPage() {
  const { t } = useTranslation()
  const canManage = usePermission('resources.edit')
  const { data, isLoading, isError, refetch } = useResources()
  const [editing, setEditing] = useState<Resource | 'new' | null>(null)
  return (
    <>
      <PageHeader
        title={t('resources.title')}
        subtitle={t('resources.subtitle')}
        actions={
          canManage && (
            <Button onClick={() => setEditing('new')}>
              <Plus className="size-4" />
              {t('resources.new')}
            </Button>
          )
        }
      />
      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-64 rounded-xl" />
          ))}
        </div>
      ) : !data?.length ? (
        <EmptyState icon={DoorOpen} title={t('resources.empty')} hint={canManage ? t('resources.emptyHintAdmin') : t('resources.emptyHint')} className="py-16" />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {data.map((r) => (
            <ResourceCard key={r.id} resource={r} onEdit={canManage ? () => setEditing(r) : undefined} />
          ))}
        </ul>
      )}
      {editing && <ResourceDialog resource={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
    </>
  )
}

function ResourceCard({ resource: r, onEdit }: { resource: Resource; onEdit?: () => void }) {
  const { t } = useTranslation()
  const photo = useAuthedBlobUrl(r.thumbnail_url)
  const Icon = ICONS[r.type]
  return (
    <li>
      <Card className={cn('h-full gap-0 overflow-hidden py-0', !r.is_active && 'opacity-70')}>
        <div className="flex h-36 items-center justify-center bg-muted">
          {r.thumbnail_url ? (
            photo ? <img src={photo} alt="" className="h-full w-full object-cover" /> : <Skeleton className="h-full w-full rounded-none" />
          ) : (
            <Icon className="size-10 text-muted-foreground/60" aria-hidden="true" />
          )}
        </div>
        <CardContent className="grid flex-1 gap-2 p-4">
          <div className="flex items-start gap-2">
            <h2 className="min-w-0 flex-1 truncate text-base font-semibold">
              <bdi>{r.name}</bdi>
            </h2>
            {onEdit && (
              <Button variant="ghost" size="icon-sm" onClick={onEdit} aria-label={t('resources.editNamed', { name: r.name })}>
                <Pencil className="size-4" />
              </Button>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="secondary" className="gap-1 font-normal">
              <Icon className="size-3" />
              {t(`resources.types.${r.type}`)}
            </Badge>
            {r.capacity && (
              <Badge variant="outline" className="gap-1 font-normal">
                <Users className="size-3" />
                {t('resources.seats', { count: r.capacity })}
              </Badge>
            )}
            {r.needs_approval && (
              <Badge variant="outline" className="gap-1 border-amber-500/50 font-normal text-amber-700 dark:text-amber-300">
                <ShieldCheck className="size-3" />
                {t('resources.needsApproval')}
              </Badge>
            )}
            {!r.is_active && <Badge variant="outline" className="font-normal">{t('resources.inactive')}</Badge>}
          </div>
          {r.location && (
            <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <MapPin className="size-3.5" />
              <bdi>{r.location}</bdi>
            </p>
          )}
          {r.description && <p className="line-clamp-2 text-sm text-muted-foreground [unicode-bidi:plaintext]">{r.description}</p>}
          <p className="text-xs text-muted-foreground">
            {r.bookable_by === 'everyone' ? t('resources.forEveryone') : t('resources.forDepartments', { names: r.department_names.join(', ') })}
          </p>
          {r.is_active && (
            <Button variant="outline" size="sm" className="mt-auto w-fit" nativeButton={false} render={<Link to={`/bookings?view=week&resource=${r.id}`} />}>
              {t('resources.viewBookings')}
            </Button>
          )}
        </CardContent>
      </Card>
    </li>
  )
}

function ResourceDialog({ resource, onClose }: { resource?: Resource; onClose: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: departments } = useDepartments()
  const [form, setForm] = useState({
    name: resource?.name ?? '',
    type: resource?.type ?? ('room' as ResourceType),
    capacity: resource?.capacity ? String(resource.capacity) : '',
    location: resource?.location ?? '',
    description: resource?.description ?? '',
    bookable_by: resource?.bookable_by ?? ('everyone' as Resource['bookable_by']),
    departments: resource?.departments ?? ([] as number[]),
    needs_approval: resource?.needs_approval ?? false,
    is_active: resource?.is_active ?? true,
  })
  const [photo, setPhoto] = useState<File | null>(null)
  const [removePhoto, setRemovePhoto] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const picker = useRef<HTMLInputElement>(null)
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm((f) => ({ ...f, [key]: value }))

  const save = useMutation({
    mutationFn: async () => {
      const data = new FormData()
      data.append('name', form.name)
      data.append('type', form.type)
      if (form.type === 'room' && form.capacity) data.append('capacity', form.capacity)
      data.append('location', form.location)
      data.append('description', form.description)
      data.append('bookable_by', form.bookable_by)
      if (form.bookable_by === 'departments') form.departments.forEach((d) => data.append('departments', String(d)))
      data.append('needs_approval', String(form.needs_approval))
      data.append('is_active', String(form.is_active))
      if (photo) data.append('photo', photo)
      else if (removePhoto) data.append('remove_photo', 'true')
      return resource ? (await api.patch<Resource>(`/resources/${resource.id}/`, data)).data : (await api.post<Resource>('/resources/', data)).data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: RESOURCES_KEY })
      toast.success(t('common.saved'))
      onClose()
    },
    onError: (e) => {
      const info = apiError(e)
      setErrors(info.fields)
      toast.error(Object.values(info.fields)[0] ?? info.message)
    },
  })

  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={resource ? t('resources.edit') : t('resources.new')}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !form.name.trim()}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <FormField id="rs-name" label={t('resources.name')} error={errors.name}>
          <Input id="rs-name" value={form.name} dir="auto" maxLength={120} onChange={(e) => set('name', e.target.value)} />
        </FormField>
        <div className="grid grid-cols-2 gap-3">
          <FormField id="rs-type" label={t('resources.type')} error={errors.type}>
            <SimpleSelect id="rs-type" value={form.type} onChange={(v) => set('type', v as ResourceType)} options={RESOURCE_TYPES.map((r) => ({ value: r, label: t(`resources.types.${r}`) }))} />
          </FormField>
          {form.type === 'room' && (
            <FormField id="rs-capacity" label={t('resources.capacity')} error={errors.capacity}>
              <Input id="rs-capacity" type="number" min={1} max={1000} value={form.capacity} onChange={(e) => set('capacity', e.target.value)} className="font-latin" />
            </FormField>
          )}
        </div>
        <FormField id="rs-location" label={t('resources.location')} error={errors.location}>
          <Input id="rs-location" value={form.location} dir="auto" maxLength={150} onChange={(e) => set('location', e.target.value)} />
        </FormField>
        <FormField id="rs-description" label={t('resources.description')}>
          <Textarea id="rs-description" value={form.description} dir="auto" onChange={(e) => set('description', e.target.value)} className="min-h-16" />
        </FormField>
        <FormField id="rs-bookable" label={t('resources.bookableBy')} error={errors.departments}>
          <SimpleSelect
            id="rs-bookable"
            value={form.bookable_by}
            onChange={(v) => set('bookable_by', v as Resource['bookable_by'])}
            options={[
              { value: 'everyone', label: t('resources.forEveryone') },
              { value: 'departments', label: t('resources.chosenDepartments') },
            ]}
          />
          {form.bookable_by === 'departments' && (
            <div className="mt-1 grid gap-2 rounded-md border p-2.5 sm:grid-cols-2">
              {(departments ?? []).map((d) => (
                <label key={d.id} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={form.departments.includes(d.id)}
                    onCheckedChange={(on) => set('departments', on ? [...form.departments, d.id] : form.departments.filter((x) => x !== d.id))}
                  />
                  <bdi>{d.name}</bdi>
                </label>
              ))}
            </div>
          )}
        </FormField>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
            <span className="grid">
              <span className="text-sm font-medium">{t('resources.needsApproval')}</span>
              <span className="text-xs text-muted-foreground">{t('resources.needsApprovalHint')}</span>
            </span>
            <Switch checked={form.needs_approval} onCheckedChange={(v) => set('needs_approval', v)} />
          </label>
          <label className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
            <span className="grid">
              <span className="text-sm font-medium">{t('resources.active')}</span>
              <span className="text-xs text-muted-foreground">{t('resources.activeHint')}</span>
            </span>
            <Switch checked={form.is_active} onCheckedChange={(v) => set('is_active', v)} />
          </label>
        </div>
        <div className="grid gap-1.5">
          <span className="text-sm font-medium">{t('resources.photo')}</span>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => picker.current?.click()}>
              {photo ? photo.name : resource?.photo_url && !removePhoto ? t('resources.replacePhoto') : t('resources.addPhoto')}
            </Button>
            {(photo || (resource?.photo_url && !removePhoto)) && (
              <Button type="button" variant="ghost" size="sm" onClick={() => (photo ? setPhoto(null) : setRemovePhoto(true))}>
                <ImageOff className="size-4" />
                {t('resources.removePhoto')}
              </Button>
            )}
            <input
              ref={picker}
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp"
              hidden
              onChange={(e) => {
                setPhoto(e.target.files?.[0] ?? null)
                setRemovePhoto(false)
                e.target.value = ''
              }}
            />
          </div>
          {errors.photo && <p className="text-xs text-destructive">{errors.photo}</p>}
        </div>
      </div>
    </FormDialog>
  )
}
