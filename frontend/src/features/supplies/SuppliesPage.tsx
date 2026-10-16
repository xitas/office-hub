import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowDownUp, Ban, Check, Package, Pencil, Plus, Search, ShoppingCart, Truck, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, FormDialog, FormField, PageHeader, SimpleSelect } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { useConfirm } from '@/lib/confirm'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import {
  itemName,
  PURCHASE_TONE,
  SUPPLIES_KEY,
  SUPPLY_CATEGORIES,
  usePurchaseRequests,
  useStockHistory,
  useSupplyItems,
  type PurchaseRequest,
  type StockKind,
  type SupplyItem,
} from '@/lib/supplies'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { cn } from '@/lib/utils'

type Tab = 'stock' | 'requests'

function useRefresh() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: SUPPLIES_KEY })
    void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
  }
}

/** Office supplies: stock (managers and admins record what comes in and goes out) and purchase requests. */
export function SuppliesPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const canManage = usePermission('inventory.edit')
  const canAdd = usePermission('inventory.create')
  const tab: Tab = params.get('tab') === 'requests' ? 'requests' : 'stock'
  const [requesting, setRequesting] = useState<SupplyItem | 'new' | null>(null)
  const [adding, setAdding] = useState(false)
  return (
    <>
      <PageHeader
        title={t('supplies.title')}
        subtitle={t('supplies.subtitle')}
        actions={
          <div className="flex flex-wrap gap-2">
            {canAdd && (
              <Button variant="outline" onClick={() => setAdding(true)}>
                <Plus className="size-4" />
                {t('supplies.addItem')}
              </Button>
            )}
            <Button onClick={() => setRequesting('new')}>
              <ShoppingCart className="size-4" />
              {t('supplies.request')}
            </Button>
          </div>
        }
      />
      <Tabs value={tab} onValueChange={(v) => setParams(v === 'stock' ? {} : { tab: String(v) }, { replace: true })} className="mb-4">
        <TabsList>
          <TabsTrigger value="stock">{t('supplies.tabs.stock')}</TabsTrigger>
          <TabsTrigger value="requests">{t(canManage ? 'supplies.tabs.requests' : 'supplies.tabs.myRequests')}</TabsTrigger>
        </TabsList>
      </Tabs>
      {tab === 'stock' ? (
        <Stock canManage={canManage} highlight={Number(params.get('item')) || null} onRequest={setRequesting} />
      ) : (
        <Requests canManage={canManage} />
      )}
      {requesting && <RequestDialog item={requesting === 'new' ? undefined : requesting} onClose={() => setRequesting(null)} />}
      {adding && <ItemDialog onClose={() => setAdding(false)} />}
    </>
  )
}

// ------------------------------------------------------------------ stock

function Stock({ canManage, highlight, onRequest }: { canManage: boolean; highlight: number | null; onRequest: (item: SupplyItem) => void }) {
  const { t, i18n } = useTranslation()
  const [q, setQ] = useState('')
  const [category, setCategory] = useState('')
  const [low, setLow] = useState(false)
  const [inactive, setInactive] = useState(false)
  const search = useDebouncedValue(q, 250)
  const { data, isLoading, isError, refetch } = useSupplyItems({ q: search, category, low, inactive })
  const [changing, setChanging] = useState<SupplyItem | null>(null)
  const [editing, setEditing] = useState<SupplyItem | null>(null)
  const lowCount = (data ?? []).filter((i) => i.is_low && i.is_active).length
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-48 flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('supplies.search')} aria-label={t('supplies.search')} className="ps-8" />
        </div>
        <div className="w-48">
          <SimpleSelect
            id="sup-cat"
            value={category}
            onChange={setCategory}
            options={[{ value: '', label: t('supplies.allCategories') }, ...SUPPLY_CATEGORIES.map((c) => ({ value: c, label: t(`supplies.categories.${c}`) }))]}
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={low} onCheckedChange={setLow} />
          {t('supplies.lowOnly')}
        </label>
        {canManage && (
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={inactive} onCheckedChange={setInactive} />
            {t('supplies.showInactive')}
          </label>
        )}
        {!low && lowCount > 0 && (
          <Badge variant="outline" className="ms-auto gap-1 border-amber-500/50 font-normal text-amber-700 dark:text-amber-300">
            <AlertTriangle className="size-3.5" />
            {t('supplies.lowCount', { count: lowCount })}
          </Badge>
        )}
      </div>
      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading ? (
        <Skeleton className="h-64 rounded-xl" />
      ) : !data?.length ? (
        <EmptyState icon={Package} title={t('supplies.noItems')} className="py-12" />
      ) : (
        <ul className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {data.map((item) => {
            const share = item.reorder_level ? Math.min(100, (item.quantity / (item.reorder_level * 3)) * 100) : 100
            return (
              <li key={item.id}>
                <Card className={cn('h-full gap-2 py-3', highlight === item.id && 'ring-2 ring-primary', !item.is_active && 'opacity-60')}>
                  <CardContent className="grid gap-2 px-4">
                    <div className="flex items-start gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium">{itemName(item, i18n.language)}</p>
                        <p className="truncate text-xs text-muted-foreground">
                          {t(`supplies.categories.${item.category}`)}
                          {item.location && <> · <bdi>{item.location}</bdi></>}
                        </p>
                      </div>
                      {item.is_low && item.is_active && (
                        <Badge variant="outline" className="shrink-0 border-amber-500/50 font-normal text-amber-700 dark:text-amber-300">
                          {item.quantity ? t('supplies.low') : t('supplies.out')}
                        </Badge>
                      )}
                      {!item.is_active && <Badge variant="outline" className="shrink-0 font-normal">{t('supplies.inactive')}</Badge>}
                    </div>
                    <p className="text-sm">
                      <span className="font-latin text-xl font-semibold">{item.quantity}</span>
                      <span className="ms-1 text-muted-foreground"><bdi>{item.unit}</bdi></span>
                      <span className="ms-2 text-xs text-muted-foreground">{t('supplies.reorderAt', { n: item.reorder_level })}</span>
                      {item.open_requests > 0 && (
                        <Badge variant="secondary" className="ms-2 font-normal">{t('supplies.openRequests', { count: item.open_requests })}</Badge>
                      )}
                    </p>
                    <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                      <div className={cn('h-full rounded-full', item.is_low ? 'bg-amber-500' : 'bg-primary')} style={{ width: `${share}%` }} />
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-1.5">
                      {item.is_active && (
                        <Button variant="ghost" size="sm" onClick={() => onRequest(item)}>
                          <ShoppingCart className="size-4" />
                          {t('supplies.requestShort')}
                        </Button>
                      )}
                      {canManage && (
                        <>
                          <Button variant="outline" size="sm" onClick={() => setChanging(item)}>
                            <ArrowDownUp className="size-4" />
                            {t('supplies.stockInOut')}
                          </Button>
                          <Button variant="ghost" size="icon-sm" onClick={() => setEditing(item)} aria-label={t('supplies.editItem', { name: item.name })}>
                            <Pencil className="size-4" />
                          </Button>
                        </>
                      )}
                    </div>
                  </CardContent>
                </Card>
              </li>
            )
          })}
        </ul>
      )}
      {changing && <StockDialog item={changing} onClose={() => setChanging(null)} />}
      {editing && <ItemDialog item={editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

function StockDialog({ item, onClose }: { item: SupplyItem; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const fmt = useFormat()
  const refresh = useRefresh()
  const [kind, setKind] = useState<StockKind>('used')
  const [amount, setAmount] = useState('1')
  const [note, setNote] = useState('')
  const history = useStockHistory(item.id)
  const after = kind === 'adjusted' ? Number(amount) : kind === 'received' ? item.quantity + Number(amount) : item.quantity - Number(amount)
  const save = useMutation({
    mutationFn: async () => api.post(`/inventory/items/${item.id}/stock/`, { kind, amount: Number(amount), note }),
    onSuccess: () => {
      refresh()
      toast.success(t('supplies.stockSaved'))
      onClose()
    },
    onError: (e) => toast.error(Object.values(apiError(e).fields)[0] ?? apiError(e).message),
  })
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={itemName(item, i18n.language)}
      description={t('supplies.inStock', { n: item.quantity, unit: item.unit })}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || amount === '' || Number.isNaN(after) || after < 0}>{t('common.save')}</Button>
        </>
      }
    >
      <div className="grid gap-4">
        <div className="grid grid-cols-3 gap-1.5" role="radiogroup" aria-label={t('supplies.change')}>
          {(['used', 'received', 'adjusted'] as const).map((k) => (
            <button
              key={k}
              type="button"
              role="radio"
              aria-checked={kind === k}
              onClick={() => setKind(k)}
              className={cn('rounded-md border px-2 py-2 text-sm', kind === k ? 'border-primary bg-primary text-primary-foreground' : 'hover:bg-muted')}
            >
              {t(`supplies.kinds.${k}`)}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <FormField id="st-amount" label={kind === 'adjusted' ? t('supplies.newCount') : t('supplies.quantity')}>
            <Input id="st-amount" type="number" min={kind === 'adjusted' ? 0 : 1} value={amount} onChange={(e) => setAmount(e.target.value)} className="font-latin" />
          </FormField>
          <div className="grid content-end pb-2 text-sm text-muted-foreground">
            {!Number.isNaN(after) && <span>{t('supplies.after', { n: after, unit: item.unit })}</span>}
          </div>
        </div>
        <FormField id="st-note" label={t('supplies.note')}>
          <Input id="st-note" value={note} dir="auto" maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder={t('supplies.notePlaceholder')} />
        </FormField>
        <div className="grid gap-1.5">
          <p className="text-sm font-medium">{t('supplies.history')}</p>
          {history.isLoading ? (
            <Skeleton className="h-16" />
          ) : !history.data?.length ? (
            <p className="text-sm text-muted-foreground">{t('supplies.noHistory')}</p>
          ) : (
            <ul className="max-h-48 divide-y overflow-y-auto rounded-md border text-sm">
              {history.data.map((h) => (
                <li key={h.id} className="flex flex-wrap items-center gap-x-2 px-2.5 py-1.5">
                  <span className={cn('w-12 font-latin font-medium', h.change > 0 ? 'text-success' : h.change < 0 ? 'text-destructive' : '')} dir="ltr">
                    {h.change > 0 ? `+${h.change}` : h.change}
                  </span>
                  <span>{t(`supplies.kinds.${h.kind}`)}</span>
                  <span className="text-muted-foreground">→ <span className="font-latin">{h.quantity_after}</span></span>
                  {h.note && <span className="min-w-0 truncate text-xs text-muted-foreground [unicode-bidi:plaintext]">{h.note}</span>}
                  <span className="ms-auto text-xs text-muted-foreground">
                    {h.by_name && <bdi>{h.by_name}</bdi>} · {fmt.dateTime(h.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </FormDialog>
  )
}

function ItemDialog({ item, onClose }: { item?: SupplyItem; onClose: () => void }) {
  const { t } = useTranslation()
  const refresh = useRefresh()
  const confirm = useConfirm()
  const canDelete = usePermission('inventory.delete')
  const [form, setForm] = useState({
    name: item?.name ?? '',
    name_ur: item?.name_ur ?? '',
    category: item?.category ?? 'stationery',
    unit: item?.unit ?? 'piece',
    quantity: '0',
    reorder_level: String(item?.reorder_level ?? 5),
    location: item?.location ?? '',
    notes: item?.notes ?? '',
    is_active: item?.is_active ?? true,
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }))
  const save = useMutation({
    mutationFn: async () => {
      const body = { ...form, reorder_level: Number(form.reorder_level), quantity: Number(form.quantity) }
      return item ? api.patch(`/inventory/items/${item.id}/`, body) : api.post('/inventory/items/', body)
    },
    onSuccess: () => {
      refresh()
      toast.success(t('common.saved'))
      onClose()
    },
    onError: (e) => {
      const err = apiError(e)
      setErrors(err.fields)
      toast.error(Object.values(err.fields)[0] ?? err.message)
    },
  })
  const remove = useMutation({
    mutationFn: async () => api.delete(`/inventory/items/${item!.id}/`),
    onSuccess: () => {
      refresh()
      toast.success(t('common.deleted'))
      onClose()
    },
    onError: (e) => toast.error(Object.values(apiError(e).fields)[0] ?? apiError(e).message),
  })
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={item ? t('supplies.editItem', { name: item.name }) : t('supplies.addItem')}
      footer={
        <>
          {item && canDelete && (
            <Button
              variant="ghost"
              className="me-auto text-destructive"
              disabled={remove.isPending}
              onClick={async () => {
                if (await confirm({ title: t('supplies.deleteTitle', { name: item.name }), description: t('supplies.deleteText'), confirmLabel: t('common.delete'), destructive: true }))
                  remove.mutate()
              }}
            >
              {t('common.delete')}
            </Button>
          )}
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !form.name.trim()}>{t('common.save')}</Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField id="it-name" label={t('supplies.name')} error={errors.name}>
          <Input id="it-name" value={form.name} maxLength={100} onChange={(e) => set('name', e.target.value)} />
        </FormField>
        <FormField id="it-name-ur" label={t('supplies.nameUr')}>
          <Input id="it-name-ur" value={form.name_ur} dir="rtl" maxLength={100} onChange={(e) => set('name_ur', e.target.value)} />
        </FormField>
        <FormField id="it-cat" label={t('supplies.category')}>
          <SimpleSelect id="it-cat" value={form.category} onChange={(v) => set('category', v as SupplyItem['category'])} options={SUPPLY_CATEGORIES.map((c) => ({ value: c, label: t(`supplies.categories.${c}`) }))} />
        </FormField>
        <FormField id="it-unit" label={t('supplies.unit')} hint={t('supplies.unitHint')}>
          <Input id="it-unit" value={form.unit} dir="auto" maxLength={30} onChange={(e) => set('unit', e.target.value)} />
        </FormField>
        {!item && (
          <FormField id="it-qty" label={t('supplies.openingCount')} error={errors.quantity}>
            <Input id="it-qty" type="number" min={0} value={form.quantity} onChange={(e) => set('quantity', e.target.value)} className="font-latin" />
          </FormField>
        )}
        <FormField id="it-level" label={t('supplies.reorderLevel')} hint={t('supplies.reorderHint')} error={errors.reorder_level}>
          <Input id="it-level" type="number" min={0} value={form.reorder_level} onChange={(e) => set('reorder_level', e.target.value)} className="font-latin" />
        </FormField>
        <FormField id="it-loc" label={t('supplies.location')}>
          <Input id="it-loc" value={form.location} dir="auto" maxLength={100} onChange={(e) => set('location', e.target.value)} />
        </FormField>
        <FormField id="it-notes" label={t('supplies.notes')} className="sm:col-span-2">
          <Input id="it-notes" value={form.notes} dir="auto" maxLength={300} onChange={(e) => set('notes', e.target.value)} />
        </FormField>
        {item && (
          <label className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm sm:col-span-2">
            {t('supplies.stocked')}
            <Switch checked={form.is_active} onCheckedChange={(v) => set('is_active', v)} />
          </label>
        )}
      </div>
    </FormDialog>
  )
}

// ------------------------------------------------------------------ purchase requests

function Requests({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation()
  const canApprove = usePermission('inventory.approve')
  const approvals = usePurchaseRequests('approvals', canApprove)
  const toReceive = usePurchaseRequests('to_receive', canManage)
  const all = usePurchaseRequests(canManage ? 'all' : 'mine')
  const section = (title: string, query: typeof all, empty: string) => (
    <section>
      <h2 className="mb-2 text-sm font-medium text-muted-foreground">{title}</h2>
      {query.isError ? (
        <ErrorState onRetry={() => void query.refetch()} />
      ) : query.isLoading ? (
        <Skeleton className="h-24 rounded-xl" />
      ) : !query.data?.length ? (
        <p className="rounded-xl border bg-card p-4 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="grid gap-2">
          {query.data.map((r) => (
            <RequestRow key={r.id} req={r} showName={canManage} />
          ))}
        </ul>
      )}
    </section>
  )
  return (
    <div className="grid gap-6">
      {canApprove && section(t('supplies.toApprove'), approvals, t('supplies.nothingToApprove'))}
      {canManage && section(t('supplies.toReceive'), toReceive, t('supplies.nothingToReceive'))}
      {section(canManage ? t('supplies.allRequests') : t('supplies.myRequests'), all, t('supplies.noRequests'))}
    </div>
  )
}

function RequestRow({ req: r, showName }: { req: PurchaseRequest; showName: boolean }) {
  const { t, i18n } = useTranslation()
  const fmt = useFormat()
  const refresh = useRefresh()
  const confirm = useConfirm()
  const [rejecting, setRejecting] = useState(false)
  const [receiving, setReceiving] = useState(false)
  const [note, setNote] = useState('')
  const act = useMutation({
    mutationFn: async (what: { cancel: true } | { approve: boolean; note?: string }) =>
      'cancel' in what ? api.post(`/inventory/requests/${r.id}/cancel/`) : api.post(`/inventory/requests/${r.id}/decide/`, what),
    onSuccess: (_d, what) => {
      refresh()
      setRejecting(false)
      toast.success('cancel' in what ? t('supplies.cancelledToast') : what.approve ? t('supplies.approvedToast') : t('supplies.rejectedToast'))
    },
    onError: (e) => toast.error(apiError(e).message),
  })
  return (
    <li>
      <Card className="gap-2 py-3">
        <CardContent className="flex flex-wrap items-center gap-3 px-4">
          <div className="min-w-0 flex-1 basis-64">
            <p className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{itemName(r, i18n.language)}</span>
              <span className="text-muted-foreground"><span className="font-latin">× {r.received_quantity ?? r.quantity}</span> <bdi>{r.unit}</bdi></span>
              <Badge variant="outline" className={cn('font-normal', PURCHASE_TONE[r.status])}>{t(`supplies.status.${r.status}`)}</Badge>
              {!r.item && <Badge variant="secondary" className="font-normal">{t('supplies.newThing')}</Badge>}
            </p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {showName && <><bdi>{r.requested_by_name}</bdi>{r.department_name && <> · <bdi>{r.department_name}</bdi></>} · </>}
              {fmt.date(r.created_at)}
              {r.estimated_cost && <> · {t('supplies.about', { amount: fmt.currency(r.estimated_cost) })}</>}
            </p>
            {r.reason && <p className="mt-1 text-sm [unicode-bidi:plaintext]">{r.reason}</p>}
            {r.decision_note && <p className="mt-1 text-xs text-muted-foreground">{t('supplies.decisionNote', { name: r.decided_by_name ?? '', note: r.decision_note })}</p>}
            {r.status === 'received' && r.received_at && (
              <p className="mt-1 text-xs text-muted-foreground">{t('supplies.receivedBy', { name: r.received_by_name ?? '', when: fmt.dateTime(r.received_at) })}</p>
            )}
            {rejecting && (
              <div className="mt-2 grid gap-2">
                <Textarea value={note} dir="auto" maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder={t('supplies.rejectNote')} aria-label={t('supplies.rejectNote')} className="min-h-14" />
                <div className="flex gap-2">
                  <Button size="sm" variant="destructive" disabled={act.isPending} onClick={() => act.mutate({ approve: false, note })}>{t('supplies.reject')}</Button>
                  <Button size="sm" variant="ghost" onClick={() => setRejecting(false)}>{t('common.cancel')}</Button>
                </div>
              </div>
            )}
          </div>
          {!rejecting && (
            <div className="flex flex-wrap gap-2">
              {r.can_decide && (
                <>
                  <Button variant="outline" size="sm" disabled={act.isPending} onClick={() => setRejecting(true)}>
                    <X className="size-4" />
                    {t('supplies.reject')}
                  </Button>
                  <Button size="sm" disabled={act.isPending} onClick={() => act.mutate({ approve: true })}>
                    <Check className="size-4" />
                    {t('supplies.approve')}
                  </Button>
                </>
              )}
              {r.can_receive && (
                <Button size="sm" onClick={() => setReceiving(true)}>
                  <Truck className="size-4" />
                  {t('supplies.markReceived')}
                </Button>
              )}
              {r.can_cancel && !r.can_decide && (
                <Button
                  variant="outline"
                  size="sm"
                  className="text-destructive"
                  disabled={act.isPending}
                  onClick={async () => {
                    if (await confirm({ title: t('supplies.cancelTitle'), description: t('supplies.cancelText'), confirmLabel: t('supplies.cancel'), cancelLabel: t('supplies.keep'), destructive: true }))
                      act.mutate({ cancel: true })
                  }}
                >
                  <Ban className="size-4" />
                  {t('supplies.cancel')}
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>
      {receiving && <ReceiveDialog req={r} onClose={() => setReceiving(false)} />}
    </li>
  )
}

function ReceiveDialog({ req, onClose }: { req: PurchaseRequest; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const refresh = useRefresh()
  const [quantity, setQuantity] = useState(String(req.quantity))
  const [addToStock, setAddToStock] = useState(true)
  const save = useMutation({
    mutationFn: async () => api.post(`/inventory/requests/${req.id}/receive/`, { quantity: Number(quantity), add_to_stock: addToStock }),
    onSuccess: () => {
      refresh()
      toast.success(t('supplies.receivedToast'))
      onClose()
    },
    onError: (e) => toast.error(Object.values(apiError(e).fields)[0] ?? apiError(e).message),
  })
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t('supplies.receiveTitle', { name: itemName(req, i18n.language) })}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || Number(quantity) < 1}>{t('supplies.markReceived')}</Button>
        </>
      }
    >
      <div className="grid gap-4">
        <FormField id="rc-qty" label={t('supplies.receivedQuantity')} hint={t('supplies.ordered', { n: req.quantity, unit: req.unit })}>
          <Input id="rc-qty" type="number" min={1} value={quantity} onChange={(e) => setQuantity(e.target.value)} className="font-latin sm:w-40" />
        </FormField>
        <label className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm">
          <span>
            {t('supplies.addToStock')}
            <span className="block text-xs text-muted-foreground">{req.item ? t('supplies.addToStockHint') : t('supplies.addNewHint')}</span>
          </span>
          <Switch checked={addToStock} onCheckedChange={setAddToStock} />
        </label>
      </div>
    </FormDialog>
  )
}

function RequestDialog({ item, onClose }: { item?: SupplyItem; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const refresh = useRefresh()
  const { data: items } = useSupplyItems()
  const [choice, setChoice] = useState(item ? String(item.id) : '')
  const [name, setName] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [unit, setUnit] = useState('')
  const [reason, setReason] = useState('')
  const [cost, setCost] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const chosen = (items ?? []).find((i) => String(i.id) === choice)
  const save = useMutation({
    mutationFn: async () =>
      api.post('/inventory/requests/', {
        item: chosen ? chosen.id : null,
        item_name: chosen ? '' : name,
        quantity: Number(quantity),
        unit: chosen ? '' : unit,
        reason,
        estimated_cost: cost || null,
      }),
    onSuccess: () => {
      refresh()
      toast.success(t('supplies.requestedToast'))
      onClose()
    },
    onError: (e) => {
      const err = apiError(e)
      setErrors(err.fields)
      toast.error(Object.values(err.fields)[0] ?? err.message)
    },
  })
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t('supplies.request')}
      description={t('supplies.requestHint')}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || Number(quantity) < 1 || (!chosen && !name.trim())}>{t('supplies.send')}</Button>
        </>
      }
    >
      <div className="grid gap-4">
        <FormField id="pr-item" label={t('supplies.what')} error={errors.item}>
          <SimpleSelect
            id="pr-item"
            value={choice}
            onChange={setChoice}
            options={[{ value: '', label: t('supplies.somethingElse') }, ...(items ?? []).map((i) => ({ value: String(i.id), label: itemName(i, i18n.language) }))]}
          />
        </FormField>
        {!chosen && (
          <div className="grid grid-cols-[1fr_8rem] gap-3">
            <FormField id="pr-name" label={t('supplies.name')} error={errors.item_name}>
              <Input id="pr-name" value={name} dir="auto" maxLength={100} onChange={(e) => setName(e.target.value)} placeholder={t('supplies.namePlaceholder')} />
            </FormField>
            <FormField id="pr-unit" label={t('supplies.unit')}>
              <Input id="pr-unit" value={unit} dir="auto" maxLength={30} onChange={(e) => setUnit(e.target.value)} />
            </FormField>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <FormField id="pr-qty" label={chosen ? t('supplies.quantityIn', { unit: chosen.unit }) : t('supplies.quantity')} error={errors.quantity}>
            <Input id="pr-qty" type="number" min={1} value={quantity} onChange={(e) => setQuantity(e.target.value)} className="font-latin" />
          </FormField>
          <FormField id="pr-cost" label={t('supplies.estimatedCost')} error={errors.estimated_cost}>
            <Input id="pr-cost" type="number" min={0} step="0.01" value={cost} onChange={(e) => setCost(e.target.value)} className="font-latin" />
          </FormField>
        </div>
        <FormField id="pr-reason" label={t('supplies.reason')}>
          <Textarea id="pr-reason" value={reason} dir="auto" maxLength={500} onChange={(e) => setReason(e.target.value)} className="min-h-16" />
        </FormField>
      </div>
    </FormDialog>
  )
}
