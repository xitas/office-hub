import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Ban, Banknote, Check, Download, FileImage, FileText, Loader2, Paperclip, Pencil, Plus, ReceiptText, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, FormDialog, FormField, PageHeader, SimpleSelect } from '@/components/common'
import { MonthNav } from '@/components/common/MonthNav'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { todayInOffice } from '@/lib/bookings'
import { useConfirm } from '@/lib/confirm'
import {
  EXPENSE_CATEGORIES,
  EXPENSE_TONE,
  EXPENSES_KEY,
  MAX_RECEIPTS,
  useExpenses,
  useExpenseSummary,
  type Expense,
  type ExpenseCategory,
  type Receipt,
} from '@/lib/expenses'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { ATTACHMENT_ACCEPT, ATTACHMENT_MAX_MB, formatBytes } from '@/lib/tasks'
import { downloadFile } from '@/lib/transfer'
import { useAuthedBlobUrl } from '@/lib/useAuthedBlob'
import { useMe } from '@/lib/auth'
import { cn } from '@/lib/utils'

type Tab = 'mine' | 'approvals' | 'team' | 'to_pay'

function useRefresh() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: EXPENSES_KEY })
    void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
  }
}

/** Expense claims: mine (with receipts), claims to approve, the team's month (managers, admins) and claims to pay (admins). */
export function ExpensesPage() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const me = useMe()
  const [params, setParams] = useSearchParams()
  const canApprove = usePermission('expenses.approve')
  const isAdmin = me.role === 'admin'
  const asked = params.get('tab')
  const tab: Tab = canApprove && (asked === 'approvals' || asked === 'team') ? asked : isAdmin && asked === 'to_pay' ? 'to_pay' : 'mine'
  const month = params.get('month') ?? todayInOffice(fmt.settings.timezone).slice(0, 7)
  const [claiming, setClaiming] = useState(false)
  const set = (changes: Record<string, string | undefined>) =>
    setParams((p) => {
      for (const [k, v] of Object.entries(changes)) {
        if (v) p.set(k, v)
        else p.delete(k)
      }
      return p
    }, { replace: true })
  return (
    <>
      <PageHeader
        title={t('expenses.title')}
        subtitle={t('expenses.subtitle')}
        actions={
          <Button onClick={() => setClaiming(true)}>
            <Plus className="size-4" />
            {t('expenses.newClaim')}
          </Button>
        }
      />
      {canApprove && (
        <Tabs value={tab} onValueChange={(v) => set({ tab: v === 'mine' ? undefined : String(v) })} className="mb-4">
          <TabsList>
            <TabsTrigger value="mine">{t('expenses.tabs.mine')}</TabsTrigger>
            <TabsTrigger value="approvals">{t('expenses.tabs.approvals')}</TabsTrigger>
            {isAdmin && <TabsTrigger value="to_pay">{t('expenses.tabs.toPay')}</TabsTrigger>}
            <TabsTrigger value="team">{t('expenses.tabs.team')}</TabsTrigger>
          </TabsList>
        </Tabs>
      )}
      {tab === 'mine' || tab === 'team' ? (
        <MonthView scope={tab === 'team' ? 'team' : 'mine'} month={month} onMonth={(m) => set({ month: m })} />
      ) : (
        <Waiting scope={tab} />
      )}
      {claiming && <ClaimDialog onClose={() => setClaiming(false)} />}
    </>
  )
}

function MonthView({ scope, month, onMonth }: { scope: 'mine' | 'team'; month: string; onMonth: (m: string) => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const list = useExpenses(scope, month)
  const summary = useExpenseSummary(scope, month)
  const s = summary.data
  const tiles = s
    ? ([
        ['pending', 'expenses.totals.pending'],
        ['approved', 'expenses.totals.approved'],
        ['paid', 'expenses.totals.paid'],
        ['rejected', 'expenses.totals.rejected'],
      ] as const)
    : []
  const categories = s ? Object.entries(s.by_category).sort((a, b) => Number(b[1]) - Number(a[1])) : []
  const top = categories.length ? Number(categories[0][1]) : 0
  return (
    <div className="grid gap-4">
      <MonthNav month={month} onMonth={onMonth} />
      {summary.isLoading ? (
        <Skeleton className="h-20 rounded-xl" />
      ) : s ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {tiles.map(([key, label]) => (
            <Card key={key} className="gap-1 py-3">
              <CardContent className="px-4">
                <p className="text-xs text-muted-foreground">{t(label, { count: s.by_status[key].count })}</p>
                <p className="mt-1 font-latin text-lg font-semibold">{fmt.currency(s.by_status[key].amount, s.currency)}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}
      {categories.length > 0 && (
        <Card className="gap-2 py-3">
          <CardContent className="grid gap-2 px-4">
            <p className="text-sm font-medium">{t('expenses.byCategory')}</p>
            <ul className="grid gap-1.5">
              {categories.map(([c, amount]) => (
                <li key={c} className="grid grid-cols-[9rem_1fr_auto] items-center gap-2 text-sm max-sm:grid-cols-[7rem_1fr_auto]">
                  <span className="truncate">{t(`expenses.categories.${c}`)}</span>
                  <span className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
                    <span className="block h-full rounded-full bg-primary" style={{ width: `${(Number(amount) / top) * 100}%` }} />
                  </span>
                  <span className="font-latin text-muted-foreground">{fmt.currency(amount, s!.currency)}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
      <ClaimList query={list} showName={scope === 'team'} empty={scope === 'team' ? t('expenses.noTeamClaims') : t('expenses.noClaims')} />
    </div>
  )
}

function Waiting({ scope }: { scope: 'approvals' | 'to_pay' }) {
  const { t } = useTranslation()
  const list = useExpenses(scope)
  return (
    <div className="grid gap-3">
      <p className="text-sm text-muted-foreground">{scope === 'approvals' ? t('expenses.approvalsHint') : t('expenses.toPayHint')}</p>
      <ClaimList query={list} showName empty={scope === 'approvals' ? t('expenses.nothingToApprove') : t('expenses.nothingToPay')} />
    </div>
  )
}

function ClaimList({ query, showName, empty }: { query: ReturnType<typeof useExpenses>; showName: boolean; empty: string }) {
  if (query.isError) return <ErrorState onRetry={() => void query.refetch()} />
  if (query.isLoading) return <Skeleton className="h-40 rounded-xl" />
  if (!query.data?.length) return <EmptyState icon={ReceiptText} title={empty} className="py-12" />
  return (
    <ul className="grid gap-2">
      {query.data.map((e) => (
        <ClaimRow key={e.id} expense={e} showName={showName} />
      ))}
    </ul>
  )
}

function ClaimRow({ expense: e, showName }: { expense: Expense; showName: boolean }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const refresh = useRefresh()
  const confirm = useConfirm()
  const [rejecting, setRejecting] = useState(false)
  const [paying, setPaying] = useState(false)
  const [editing, setEditing] = useState(false)
  const [note, setNote] = useState('')
  const act = useMutation({
    mutationFn: async (what: { cancel: true } | { approve: boolean; note?: string }) =>
      'cancel' in what ? api.post(`/expenses/claims/${e.id}/cancel/`) : api.post(`/expenses/claims/${e.id}/decide/`, what),
    onSuccess: (_d, what) => {
      refresh()
      setRejecting(false)
      toast.success('cancel' in what ? t('expenses.cancelledToast') : what.approve ? t('expenses.approvedToast') : t('expenses.rejectedToast'))
    },
    onError: (err) => toast.error(apiError(err).message),
  })
  return (
    <li>
      <Card className="gap-2 py-3">
        <CardContent className="grid gap-2 px-4">
          <div className="flex flex-wrap items-start gap-3">
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-center gap-2">
                {showName && <bdi className="font-medium">{e.user_name}</bdi>}
                <span className={cn(!showName && 'font-medium', '[unicode-bidi:plaintext]')}>{e.title}</span>
                <Badge variant="outline" className={cn('font-normal', EXPENSE_TONE[e.status])}>{t(`expenses.status.${e.status}`)}</Badge>
              </p>
              <p className="mt-0.5 text-sm text-muted-foreground">
                {t(`expenses.categories.${e.category}`)} · {fmt.date(`${e.spent_on}T12:00:00`)}
                {showName && e.department_name && <> · <bdi>{e.department_name}</bdi></>}
                {!e.receipts.length && <> · <span className="text-amber-700 dark:text-amber-300">{t('expenses.noReceipt')}</span></>}
              </p>
            </div>
            <p className="font-latin text-lg font-semibold">{fmt.currency(e.amount, e.currency)}</p>
          </div>
          {e.description && <p className="text-sm [unicode-bidi:plaintext]">{e.description}</p>}
          {e.receipts.length > 0 && (
            <ul className="flex flex-wrap gap-2">
              {e.receipts.map((r) => (
                <ReceiptChip key={r.id} receipt={r} />
              ))}
            </ul>
          )}
          {e.decision_note && <p className="text-xs text-muted-foreground">{t('expenses.decisionNote', { name: e.decided_by_name ?? '', note: e.decision_note })}</p>}
          {e.status === 'paid' && e.paid_at && (
            <p className="text-xs text-muted-foreground">
              {t('expenses.paidBy', { name: e.paid_by_name ?? '', when: fmt.dateTime(e.paid_at) })}
              {e.payment_note && <> · <bdi>{e.payment_note}</bdi></>}
            </p>
          )}
          {rejecting ? (
            <div className="grid gap-2">
              <Textarea value={note} dir="auto" maxLength={300} onChange={(ev) => setNote(ev.target.value)} placeholder={t('expenses.rejectNote')} aria-label={t('expenses.rejectNote')} className="min-h-14" />
              <div className="flex gap-2">
                <Button size="sm" variant="destructive" disabled={act.isPending} onClick={() => act.mutate({ approve: false, note })}>{t('expenses.reject')}</Button>
                <Button size="sm" variant="ghost" onClick={() => setRejecting(false)}>{t('common.cancel')}</Button>
              </div>
            </div>
          ) : (
            (e.can_decide || e.can_pay || e.can_edit || e.can_cancel) && (
              <div className="flex flex-wrap justify-end gap-2">
                {e.can_edit && (
                  <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
                    <Pencil className="size-4" />
                    {t('expenses.edit')}
                  </Button>
                )}
                {e.can_cancel && !e.can_decide && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-destructive"
                    disabled={act.isPending}
                    onClick={async () => {
                      if (await confirm({ title: t('expenses.cancelTitle'), description: t('expenses.cancelText'), confirmLabel: t('expenses.cancel'), cancelLabel: t('expenses.keep'), destructive: true }))
                        act.mutate({ cancel: true })
                    }}
                  >
                    <Ban className="size-4" />
                    {t('expenses.cancel')}
                  </Button>
                )}
                {e.can_decide && (
                  <>
                    <Button variant="outline" size="sm" disabled={act.isPending} onClick={() => setRejecting(true)}>
                      <X className="size-4" />
                      {t('expenses.reject')}
                    </Button>
                    <Button size="sm" disabled={act.isPending} onClick={() => act.mutate({ approve: true })}>
                      <Check className="size-4" />
                      {t('expenses.approve')}
                    </Button>
                  </>
                )}
                {e.can_pay && (
                  <Button size="sm" onClick={() => setPaying(true)}>
                    <Banknote className="size-4" />
                    {t('expenses.markPaid')}
                  </Button>
                )}
              </div>
            )
          )}
        </CardContent>
      </Card>
      {paying && <PayDialog expense={e} onClose={() => setPaying(false)} />}
      {editing && <ClaimDialog expense={e} onClose={() => setEditing(false)} />}
    </li>
  )
}

function ReceiptChip({ receipt: r }: { receipt: Receipt }) {
  const { t } = useTranslation()
  const thumb = useAuthedBlobUrl(r.thumbnail_url)
  const [previewing, setPreviewing] = useState(false)
  const open = async () => {
    if (r.kind === 'image') {
      setPreviewing(true)
      return
    }
    try {
      await downloadFile(r.download_url, {}, r.original_name)
    } catch {
      toast.error(t('transfer.exportFailed'))
    }
  }
  return (
    <li>
      <button
        type="button"
        onClick={() => void open()}
        className="flex items-center gap-2 rounded-md border p-1.5 pe-3 text-start text-sm hover:bg-muted"
        aria-label={t('expenses.openReceipt', { name: r.original_name })}
      >
        <span className="flex size-10 shrink-0 items-center justify-center overflow-hidden rounded bg-muted">
          {thumb ? <img src={thumb} alt="" className="size-full object-cover" /> : r.kind === 'image' ? <FileImage className="size-4 text-muted-foreground" /> : <FileText className="size-4 text-muted-foreground" />}
        </span>
        <span className="min-w-0">
          <bdi className="block max-w-40 truncate">{r.original_name}</bdi>
          <span className="flex items-center gap-1 font-latin text-xs text-muted-foreground">
            <bdi dir="ltr">{formatBytes(r.size)}</bdi>
            {r.kind !== 'image' && <Download className="size-3" />}
          </span>
        </span>
      </button>
      {previewing && <ReceiptPreview receipt={r} onClose={() => setPreviewing(false)} />}
    </li>
  )
}

function ReceiptPreview({ receipt, onClose }: { receipt: Receipt; onClose: () => void }) {
  const src = useAuthedBlobUrl(`${receipt.download_url}?inline=1`)
  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={receipt.original_name}>
      <div className="flex min-h-40 items-center justify-center rounded-md bg-muted">
        {src ? <img src={src} alt={receipt.original_name} className="max-h-[70dvh] w-auto rounded-md object-contain" /> : <Loader2 className="size-6 animate-spin text-muted-foreground" />}
      </div>
    </FormDialog>
  )
}

function PayDialog({ expense, onClose }: { expense: Expense; onClose: () => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const refresh = useRefresh()
  const [note, setNote] = useState('')
  const pay = useMutation({
    mutationFn: async () => api.post(`/expenses/claims/${expense.id}/pay/`, { note }),
    onSuccess: () => {
      refresh()
      toast.success(t('expenses.paidToast'))
      onClose()
    },
    onError: (err) => toast.error(apiError(err).message),
  })
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t('expenses.payTitle', { name: expense.user_name })}
      description={`${expense.title} · ${fmt.currency(expense.amount, expense.currency)}`}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => pay.mutate()} disabled={pay.isPending}>{t('expenses.markPaid')}</Button>
        </>
      }
    >
      <FormField id="pay-note" label={t('expenses.paymentNote')} hint={t('expenses.paymentNoteHint')}>
        <Input id="pay-note" value={note} dir="auto" maxLength={200} onChange={(ev) => setNote(ev.target.value)} />
      </FormField>
    </FormDialog>
  )
}

function ClaimDialog({ expense, onClose }: { expense?: Expense; onClose: () => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const refresh = useRefresh()
  const today = todayInOffice(fmt.settings.timezone)
  const [form, setForm] = useState({
    title: expense?.title ?? '',
    category: expense?.category ?? ('travel' as ExpenseCategory),
    amount: expense ? String(Number(expense.amount)) : '',
    spent_on: expense?.spent_on ?? today,
    description: expense?.description ?? '',
  })
  const [files, setFiles] = useState<File[]>([])
  const [removed, setRemoved] = useState<number[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const picker = useRef<HTMLInputElement>(null)
  const kept = (expense?.receipts ?? []).filter((r) => !removed.includes(r.id))
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }))
  const save = useMutation({
    mutationFn: async () => {
      const body = new FormData()
      for (const [k, v] of Object.entries(form)) body.append(k, v)
      files.forEach((f) => body.append('files', f))
      removed.forEach((id) => body.append('remove_receipts', String(id)))
      return expense ? api.patch(`/expenses/claims/${expense.id}/`, body) : api.post('/expenses/claims/', body)
    },
    onSuccess: () => {
      refresh()
      toast.success(t(expense ? 'common.saved' : 'expenses.claimedToast'))
      onClose()
    },
    onError: (err) => {
      const info = apiError(err)
      setErrors(info.fields)
      toast.error(Object.values(info.fields)[0] ?? info.message)
    },
  })
  const valid = form.title.trim() && Number(form.amount) > 0 && form.spent_on
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={expense ? t('expenses.editTitle') : t('expenses.newClaim')}
      description={t('expenses.claimHint')}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !valid}>
            {save.isPending && <Loader2 className="size-4 animate-spin" />}
            {expense ? t('common.save') : t('expenses.submit')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <FormField id="ex-title" label={t('expenses.what')} error={errors.title}>
          <Input id="ex-title" value={form.title} dir="auto" maxLength={120} onChange={(ev) => set('title', ev.target.value)} placeholder={t('expenses.whatPlaceholder')} />
        </FormField>
        <div className="grid gap-3 sm:grid-cols-3">
          <FormField id="ex-cat" label={t('expenses.category')}>
            <SimpleSelect id="ex-cat" value={form.category} onChange={(v) => set('category', v as ExpenseCategory)} options={EXPENSE_CATEGORIES.map((c) => ({ value: c, label: t(`expenses.categories.${c}`) }))} />
          </FormField>
          <FormField id="ex-amount" label={t('expenses.amountIn', { currency: fmt.settings.currency })} error={errors.amount}>
            <Input id="ex-amount" type="number" min={0.01} step="0.01" value={form.amount} onChange={(ev) => set('amount', ev.target.value)} className="font-latin" />
          </FormField>
          <FormField id="ex-date" label={t('expenses.spentOn')} error={errors.spent_on}>
            <Input id="ex-date" type="date" max={today} value={form.spent_on} onChange={(ev) => set('spent_on', ev.target.value)} className="font-latin" />
          </FormField>
        </div>
        <FormField id="ex-desc" label={t('expenses.description')}>
          <Textarea id="ex-desc" value={form.description} dir="auto" maxLength={2000} onChange={(ev) => set('description', ev.target.value)} className="min-h-16" />
        </FormField>
        <div className="grid gap-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium">{t('expenses.receipts')}</span>
            <Button type="button" variant="outline" size="sm" onClick={() => picker.current?.click()} disabled={kept.length + files.length >= MAX_RECEIPTS}>
              <Paperclip className="size-4" />
              {t('expenses.addReceipt')}
            </Button>
            <input
              ref={picker}
              type="file"
              multiple
              hidden
              accept={ATTACHMENT_ACCEPT}
              onChange={(ev) => {
                const picked = Array.from(ev.target.files ?? [])
                setFiles((f) => [...f, ...picked].slice(0, MAX_RECEIPTS - kept.length))
                ev.target.value = ''
              }}
            />
          </div>
          {errors.files && <p className="text-xs text-destructive">{errors.files}</p>}
          {kept.length + files.length > 0 ? (
            <ul className="grid gap-1.5">
              {kept.map((r) => (
                <FileRow key={`r${r.id}`} name={r.original_name} onRemove={() => setRemoved((x) => [...x, r.id])} />
              ))}
              {files.map((f, i) => (
                <FileRow key={`f${i}`} name={f.name} isNew onRemove={() => setFiles((list) => list.filter((_, j) => j !== i))} />
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">{t('expenses.receiptsHint', { n: MAX_RECEIPTS, mb: ATTACHMENT_MAX_MB })}</p>
          )}
        </div>
      </div>
    </FormDialog>
  )
}

function FileRow({ name, isNew, onRemove }: { name: string; isNew?: boolean; onRemove: () => void }) {
  const { t } = useTranslation()
  return (
    <li className={cn('flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm', isNew && 'border-dashed')}>
      <Paperclip className="size-3.5 shrink-0 text-muted-foreground" />
      <bdi className="min-w-0 flex-1 truncate">{name}</bdi>
      <Button type="button" variant="ghost" size="icon-xs" onClick={onRemove} aria-label={t('expenses.removeReceipt', { name })}>
        <X className="size-3.5" />
      </Button>
    </li>
  )
}
