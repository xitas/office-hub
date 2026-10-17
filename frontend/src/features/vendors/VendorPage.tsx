import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Globe, Lock, Package, Pencil, ReceiptText, ShoppingCart, Star, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ErrorState, PageHeader } from '@/components/common'
import { ContactButtons } from '@/components/common/ContactButtons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { TemplateSendButtons } from '@/features/templates/SendWithTemplate'
import { Timeline } from '@/features/timeline/Timeline'
import { api, apiError } from '@/lib/api'
import { useConfirm } from '@/lib/confirm'
import { EXPENSE_TONE, type ExpenseStatus } from '@/lib/expenses'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { itemName, PURCHASE_TONE, type PurchaseStatus } from '@/lib/supplies'
import { cn } from '@/lib/utils'
import { categoryName, useVendor, useVendorActivity, useVendorCategories, VENDORS_KEY } from '@/lib/vendors'
import { Stars, VendorDialog } from './VendorDialog'

/** One vendor: details, what the office buys and spends with them, and the calls, messages and notes. */
export function VendorPage() {
  const { t, i18n } = useTranslation()
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const confirm = useConfirm()
  const { data: v, isLoading, isError, refetch } = useVendor(id)
  const { data: categories } = useVendorCategories()
  const [editing, setEditing] = useState(false)
  const canDelete = usePermission('vendors.delete')
  const remove = useMutation({
    mutationFn: async () => api.delete(`/vendors/${id}/`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: VENDORS_KEY })
      toast.success(t('common.deleted'))
      navigate('/vendors')
    },
    onError: (e) => toast.error(Object.values(apiError(e).fields)[0] ?? apiError(e).message),
  })
  if (isError) return <ErrorState onRetry={() => void refetch()} />
  if (isLoading || !v) return <Skeleton className="h-96 rounded-xl" />
  const cats = (categories ?? []).filter((c) => v.categories.includes(c.id))
  const rows: { label: string; value: React.ReactNode }[] = [
    { label: t('vendors.fields.contact_person'), value: v.contact_person && <bdi>{v.contact_person}</bdi> },
    { label: t('vendors.fields.phone'), value: v.phone && <bdi dir="ltr" className="font-latin">{v.phone}</bdi> },
    { label: t('vendors.fields.whatsapp'), value: v.whatsapp && <bdi dir="ltr" className="font-latin">{v.whatsapp}</bdi> },
    { label: t('vendors.fields.email'), value: v.email && <a href={`mailto:${v.email}`} className="font-latin text-primary hover:underline">{v.email}</a> },
    { label: t('vendors.fields.address'), value: v.address && <span className="[unicode-bidi:plaintext]">{v.address}</span> },
    { label: t('vendors.fields.city'), value: v.city && <bdi>{v.city}</bdi> },
    { label: t('vendors.fields.areas'), value: v.areas && <span className="[unicode-bidi:plaintext]">{v.areas}</span> },
    { label: t('vendors.fields.payment_terms'), value: v.payment_terms && <span className="[unicode-bidi:plaintext]">{v.payment_terms}</span> },
    { label: t('vendors.fields.website'), value: v.website && (
      <a href={v.website} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-latin text-primary hover:underline">
        <Globe className="size-3.5" />{v.website.replace(/^https?:\/\//, '')}
      </a>
    ) },
  ]
  return (
    <>
      <Link to="/vendors" className="mb-2 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4 rtl:rotate-180" />
        {t('vendors.title')}
      </Link>
      <PageHeader
        title={v.name}
        subtitle={cats.map((c) => categoryName(c, i18n.language)).join(' · ') || undefined}
        actions={
          <div className="flex flex-wrap gap-2">
            {canDelete && (
              <Button
                variant="ghost"
                className="text-destructive"
                disabled={remove.isPending}
                onClick={async () => {
                  if (await confirm({ title: t('vendors.deleteTitle', { name: v.name }), description: t('vendors.deleteText'), confirmLabel: t('common.delete'), destructive: true }))
                    remove.mutate()
                }}
              >
                <Trash2 className="size-4" />
                {t('common.delete')}
              </Button>
            )}
            <Button variant="outline" onClick={() => setEditing(true)}>
              <Pencil className="size-4" />
              {t('vendors.edit')}
            </Button>
          </div>
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="grid content-start gap-4">
          <Card>
            <CardContent className="grid gap-3">
              <div className="flex flex-wrap items-center gap-2">
                {v.preferred && (
                  <Badge variant="outline" className="gap-1 border-amber-400/60 font-normal text-amber-700 dark:text-amber-300">
                    <Star className="size-3.5 fill-amber-400 text-amber-400" />
                    {t('vendors.preferred')}
                  </Badge>
                )}
                {!v.is_active && <Badge variant="outline" className="font-normal">{t('vendors.inactive')}</Badge>}
                <Stars value={v.rating} />
              </div>
              <dl className="grid gap-2 text-sm">
                {rows.filter((r) => r.value).map(({ label, value }) => (
                  <div key={label} className="grid grid-cols-[8rem_1fr] gap-2">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="min-w-0 break-words">{value}</dd>
                  </div>
                ))}
              </dl>
              {v.notes && <p className="rounded-md bg-muted p-3 text-sm whitespace-pre-line [unicode-bidi:plaintext]">{v.notes}</p>}
              <ContactButtons phone={v.phone} whatsapp={v.whatsapp} email={v.email}
                logFor={{ target: { vendor: v.id }, name: v.name, hint: v.contact_person, type: 'vendor' }} />
              <div className="flex flex-wrap gap-2">
                <TemplateSendButtons contact={{ id: v.id, isVendor: true, full_name: v.name, company_name: v.contact_person, phone: v.phone, whatsapp: v.whatsapp, email: v.email }} />
              </div>
            </CardContent>
          </Card>
          <Activity vendorId={v.id} />
        </div>
        <div className="lg:col-span-2">
          <Timeline target={{ vendor: v.id }} />
        </div>
      </div>
      {editing && <VendorDialog vendor={v} onClose={() => setEditing(false)} />}
    </>
  )
}

function Activity({ vendorId }: { vendorId: number }) {
  const { t, i18n } = useTranslation()
  const fmt = useFormat()
  const { data, isLoading } = useVendorActivity(vendorId)
  if (isLoading || !data) return <Skeleton className="h-40 rounded-xl" />
  return (
    <>
      <Card className="gap-3">
        <CardHeader className="flex flex-row items-center gap-2">
          <Package className="size-4 text-muted-foreground" />
          <CardTitle className="text-sm font-medium">{t('vendors.supplies')}</CardTitle>
        </CardHeader>
        <CardContent>
          {!data.supplies.length ? (
            <p className="text-sm text-muted-foreground">{t('vendors.noSupplies')}</p>
          ) : (
            <ul className="grid gap-1.5 text-sm">
              {data.supplies.map((s) => (
                <li key={s.id} className="flex items-center gap-2">
                  <Link to={`/supplies?item=${s.id}`} className="min-w-0 flex-1 truncate hover:underline">{itemName(s, i18n.language)}</Link>
                  <span className={cn('text-muted-foreground', s.is_low && 'text-amber-700 dark:text-amber-300')}>
                    <span className="font-latin">{s.quantity}</span> <bdi>{s.unit}</bdi>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      {data.purchases && (
        <Card className="gap-3">
          <CardHeader className="flex flex-row items-center gap-2">
            <ShoppingCart className="size-4 text-muted-foreground" />
            <CardTitle className="text-sm font-medium">{t('vendors.purchases')}</CardTitle>
          </CardHeader>
          <CardContent>
            {!data.purchases.length ? (
              <p className="text-sm text-muted-foreground">{t('vendors.noPurchases')}</p>
            ) : (
              <ul className="grid gap-2 text-sm">
                {data.purchases.map((p) => (
                  <li key={p.id} className="flex flex-wrap items-center gap-x-2">
                    <span className="min-w-0 flex-1">
                      {itemName(p, i18n.language)} <span className="text-muted-foreground"><span className="font-latin">× {p.quantity}</span> <bdi>{p.unit}</bdi></span>
                    </span>
                    <Badge variant="outline" className={cn('font-normal', PURCHASE_TONE[p.status as PurchaseStatus])}>{t(`supplies.status.${p.status}`)}</Badge>
                    <span className="w-full text-xs text-muted-foreground"><bdi>{p.requested_by_name}</bdi> · {fmt.date(p.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}
      {data.expenses && (
        <Card className="gap-3">
          <CardHeader className="flex flex-row items-center gap-2">
            <ReceiptText className="size-4 text-muted-foreground" />
            <CardTitle className="flex-1 text-sm font-medium">{t('vendors.expenses')}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2">
            <p className="text-sm">
              {t('vendors.spentThisYear', { count: data.expenses.year_count })}{' '}
              <span className="font-latin font-semibold">{fmt.currency(data.expenses.year_total, data.expenses.currency)}</span>
            </p>
            {data.expenses.recent.length > 0 && (
              <ul className="grid gap-2 text-sm">
                {data.expenses.recent.map((e) => (
                  <li key={e.id} className="flex flex-wrap items-center gap-x-2">
                    <span className="min-w-0 flex-1 truncate [unicode-bidi:plaintext]">{e.title}</span>
                    <span className="font-latin">{fmt.currency(e.amount, e.currency)}</span>
                    <Badge variant="outline" className={cn('font-normal', EXPENSE_TONE[e.status as ExpenseStatus])}>{t(`expenses.status.${e.status}`)}</Badge>
                    <span className="w-full text-xs text-muted-foreground"><bdi>{e.user_name}</bdi> · {fmt.date(`${e.spent_on}T12:00:00`)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}
      <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
        <Lock className="mt-0.5 size-3.5 shrink-0" />
        {t('vendors.privacyHint')}
      </p>
    </>
  )
}
