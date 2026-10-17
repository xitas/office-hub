import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MapPin, Plus, Search, Settings2, Star, Store, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, FormDialog, PageHeader, Pagination, SimpleSelect } from '@/components/common'
import { ContactButtons } from '@/components/common/ContactButtons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { api, apiError } from '@/lib/api'
import { usePermission } from '@/lib/permissions'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { cn } from '@/lib/utils'
import { categoryName, useVendorCategories, useVendorCities, useVendors, VENDORS_KEY, type VendorCategory } from '@/lib/vendors'
import { Stars, VendorDialog } from './VendorDialog'

/** The office's vendors and suppliers: search by name, phone, area; filter by service and city. */
export function VendorsPage() {
  const { t, i18n } = useTranslation()
  const [params, setParams] = useSearchParams()
  const canCurate = usePermission('vendors.delete')
  const canManage = usePermission('vendors.manage')
  const [q, setQ] = useState(params.get('q') ?? '')
  const search = useDebouncedValue(q, 250)
  const category = params.get('category') ?? ''
  const city = params.get('city') ?? ''
  const preferred = params.get('preferred') === '1'
  const inactive = params.get('inactive') === '1'
  const page = Number(params.get('page')) || 1
  const { data, isLoading, isError, refetch } = useVendors({ q: search, category, city, preferred, inactive, page })
  const { data: categories } = useVendorCategories()
  const { data: cities } = useVendorCities()
  const [adding, setAdding] = useState(false)
  const [managing, setManaging] = useState(false)
  const byId = new Map((categories ?? []).map((c) => [c.id, c]))
  const set = (changes: Record<string, string | undefined>) =>
    setParams((p) => {
      for (const [k, v] of Object.entries(changes)) {
        if (v) p.set(k, v)
        else p.delete(k)
      }
      if (!('page' in changes)) p.delete('page')
      return p
    }, { replace: true })
  return (
    <>
      <PageHeader
        title={t('vendors.title')}
        subtitle={t('vendors.subtitle')}
        actions={
          <div className="flex flex-wrap gap-2">
            {canManage && (
              <Button variant="outline" onClick={() => setManaging(true)}>
                <Settings2 className="size-4" />
                {t('vendors.categories')}
              </Button>
            )}
            <Button onClick={() => setAdding(true)}>
              <Plus className="size-4" />
              {t('vendors.add')}
            </Button>
          </div>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-52 flex-1 sm:max-w-sm">
          <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('vendors.search')} aria-label={t('vendors.search')} className="ps-8" />
        </div>
        <div className="w-52">
          <SimpleSelect
            id="vendor-category"
            value={category}
            onChange={(v) => set({ category: v })}
            options={[{ value: '', label: t('vendors.allCategories') }, ...(categories ?? []).map((c) => ({ value: String(c.id), label: categoryName(c, i18n.language) }))]}
          />
        </div>
        <div className="w-40">
          <SimpleSelect
            id="vendor-city"
            value={city}
            onChange={(v) => set({ city: v })}
            options={[{ value: '', label: t('vendors.allCities') }, ...(cities ?? []).map((c) => ({ value: c, label: c }))]}
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={preferred} onCheckedChange={(v) => set({ preferred: v ? '1' : undefined })} />
          {t('vendors.preferredOnly')}
        </label>
        {canCurate && (
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={inactive} onCheckedChange={(v) => set({ inactive: v ? '1' : undefined })} />
            {t('vendors.showInactive')}
          </label>
        )}
      </div>
      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading || !data ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : !data.results.length ? (
        <EmptyState icon={Store} title={t('vendors.none')} hint={t('vendors.noneHint')} className="py-12" />
      ) : (
        <>
          <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {data.results.map((v) => (
              <li key={v.id}>
                <Card className={cn('h-full gap-2 py-4', !v.is_active && 'opacity-60')}>
                  <CardContent className="grid gap-2 px-4">
                    <div className="flex items-start gap-2">
                      <div className="min-w-0 flex-1">
                        <Link to={`/vendors/${v.id}`} className="flex items-center gap-1.5 font-medium hover:underline">
                          {v.preferred && <Star className="size-4 shrink-0 fill-amber-400 text-amber-400" aria-label={t('vendors.preferred')} />}
                          <bdi className="truncate">{v.name}</bdi>
                        </Link>
                        {v.contact_person && <p className="truncate text-sm text-muted-foreground"><bdi>{v.contact_person}</bdi></p>}
                      </div>
                      <Stars value={v.rating} />
                    </div>
                    {v.categories.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {v.categories.map((id) => byId.get(id)).filter((c): c is VendorCategory => !!c).map((c) => (
                          <Badge key={c.id} variant="secondary" className="font-normal">{categoryName(c, i18n.language)}</Badge>
                        ))}
                      </div>
                    )}
                    {(v.city || v.areas) && (
                      <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
                        <MapPin className="mt-0.5 size-3.5 shrink-0" />
                        <span className="min-w-0 [unicode-bidi:plaintext]">{[v.city, v.areas].filter(Boolean).join(' · ')}</span>
                      </p>
                    )}
                    {!v.is_active && <Badge variant="outline" className="w-fit font-normal">{t('vendors.inactive')}</Badge>}
                    <ContactButtons phone={v.phone} whatsapp={v.whatsapp} email={v.email} className="mt-1 flex flex-wrap gap-2"
                      logFor={{ target: { vendor: v.id }, name: v.name, hint: v.contact_person, type: 'vendor' }} />
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
          <Pagination page={page} count={data.count} onPage={(p) => set({ page: p > 1 ? String(p) : undefined })} />
        </>
      )}
      {adding && <VendorDialog onClose={() => setAdding(false)} />}
      {managing && <CategoriesDialog onClose={() => setManaging(false)} />}
    </>
  )
}

/** Admins: add, rename, translate and retire service categories. */
function CategoriesDialog({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const { data } = useVendorCategories()
  const [name, setName] = useState('')
  const [nameUr, setNameUr] = useState('')
  const refresh = () => void queryClient.invalidateQueries({ queryKey: VENDORS_KEY })
  const add = useMutation({
    mutationFn: async () => api.post('/vendors/categories/', { name, name_ur: nameUr, position: (data?.length ?? 0) + 1 }),
    onSuccess: () => {
      refresh()
      setName('')
      setNameUr('')
    },
    onError: (e) => toast.error(Object.values(apiError(e).fields)[0] ?? apiError(e).message),
  })
  const change = useMutation({
    mutationFn: async ({ id, body }: { id: number; body: Partial<VendorCategory> | null }) =>
      body ? api.patch(`/vendors/categories/${id}/`, body) : api.delete(`/vendors/categories/${id}/`),
    onSuccess: refresh,
    onError: (e) => toast.error(apiError(e).message),
  })
  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={t('vendors.categories')} description={t('vendors.categoriesHint')}>
      <div className="grid gap-4">
        <ul className="divide-y rounded-md border">
          {(data ?? []).map((c) => (
            <li key={c.id} className={cn('flex flex-wrap items-center gap-2 px-3 py-2 text-sm', !c.is_active && 'opacity-60')}>
              <span className="min-w-0 flex-1">
                {categoryName(c, i18n.language)}
                {i18n.language !== 'ur' && c.name_ur && <span className="ms-2 text-muted-foreground">{c.name_ur}</span>}
              </span>
              <span className="text-xs text-muted-foreground">{t('vendors.vendorCount', { count: c.vendor_count })}</span>
              <Switch checked={c.is_active} onCheckedChange={(v) => change.mutate({ id: c.id, body: { is_active: v } })} aria-label={t('vendors.categoryActive', { name: c.name })} />
              {c.vendor_count === 0 && (
                <Button variant="ghost" size="icon-xs" onClick={() => change.mutate({ id: c.id, body: null })} aria-label={t('vendors.deleteCategory', { name: c.name })}>
                  <Trash2 className="size-3.5" />
                </Button>
              )}
            </li>
          ))}
        </ul>
        <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
          <Input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder={t('vendors.categoryName')} aria-label={t('vendors.categoryName')} />
          <Input value={nameUr} dir="rtl" maxLength={80} onChange={(e) => setNameUr(e.target.value)} placeholder={t('vendors.categoryNameUr')} aria-label={t('vendors.categoryNameUr')} />
          <Button onClick={() => add.mutate()} disabled={add.isPending || !name.trim()}>
            <Plus className="size-4" />
            {t('vendors.addCategory')}
          </Button>
        </div>
      </div>
    </FormDialog>
  )
}
