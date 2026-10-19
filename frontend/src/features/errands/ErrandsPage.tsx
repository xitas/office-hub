import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Ban, Camera, Check, CheckSquare, Hand, Loader2, MapPin, Navigation, Pencil, Plus, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, FormDialog, FormField, PageHeader } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import {
  ERRAND_ICONS, ERRAND_TONE, ERRANDS_KEY, MAX_ERRAND_PHOTOS, errandRecordLink, useErrand, useErrands, type Errand, type ErrandPhoto, type ErrandScope,
} from '@/lib/errands'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { useAuthedBlobUrl } from '@/lib/useAuthedBlob'
import { cn } from '@/lib/utils'
import { PHOTO_ACCEPT } from '@/lib/visits'
import { ErrandDialog } from './ErrandDialog'

const TABS: ErrandScope[] = ['mine', 'requested', 'open', 'team', 'done']

function useRefresh() {
  const queryClient = useQueryClient()
  return () => {
    for (const key of [ERRANDS_KEY, ['timeline'], ['map'], ['dashboard']]) void queryClient.invalidateQueries({ queryKey: key })
  }
}

/** Errands and deliveries: mine to do, ones I asked for, my department's waiting for someone, the team's, finished. */
export function ErrandsPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const canManage = usePermission('errands.delete')
  const asked = params.get('tab') as ErrandScope | null
  const tab: ErrandScope = asked && TABS.includes(asked) && (asked !== 'team' || canManage) ? asked : 'mine'
  const openId = Number(params.get('errand')) || null
  const [asking, setAsking] = useState(false)
  const set = (key: string, value?: string) =>
    setParams((p) => {
      if (value) p.set(key, value)
      else p.delete(key)
      return p
    }, { replace: true })
  return (
    <>
      <PageHeader title={t('errands.title')} subtitle={t('errands.subtitle')}
        actions={<Button onClick={() => setAsking(true)}><Plus className="size-4" />{t('errands.new')}</Button>} />
      <Tabs value={tab} onValueChange={(v) => set('tab', v === 'mine' ? undefined : String(v))} className="mb-4 max-w-full overflow-x-auto">
        <TabsList>
          {TABS.filter((s) => s !== 'team' || canManage).map((s) => <TabsTrigger key={s} value={s}>{t(`errands.tabs.${s}`)}</TabsTrigger>)}
        </TabsList>
      </Tabs>
      <ErrandList scope={tab} />
      {asking && <ErrandDialog onClose={() => setAsking(false)} />}
      {openId && <ErrandDetails id={openId} onClose={() => set('errand')} />}
    </>
  )
}

function ErrandList({ scope }: { scope: ErrandScope }) {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useErrands({ scope })
  if (isError) return <ErrorState onRetry={() => void refetch()} />
  if (isLoading || !data) return <Skeleton className="h-48 rounded-xl" />
  if (!data.length) return <EmptyState icon={Hand} title={t(`errands.empty.${scope}`)} className="py-12" />
  return (
    <ul className="grid gap-2">
      {data.map((e) => <ErrandRow key={e.id} errand={e} />)}
    </ul>
  )
}

/** "By 20/10/2026 3:00 pm" (red when late); bare: just the date and time, under a "By" label. */
export function DueText({ errand: e, bare }: { errand: Pick<Errand, 'due_at' | 'status'>; bare?: boolean }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const [now] = useState(() => Date.now())
  if (!e.due_at) return <span className="text-muted-foreground">{t('errands.noDue')}</span>
  const late = ['open', 'assigned', 'on_the_way'].includes(e.status) && new Date(e.due_at).getTime() < now
  return (
    <span className={cn(late && 'font-medium text-destructive')}>
      {bare ? `${fmt.date(e.due_at)} ${fmt.time(e.due_at)}` : t('errands.dueBy', { when: `${fmt.date(e.due_at)} ${fmt.time(e.due_at)}` })}
    </span>
  )
}

function ErrandRow({ errand: e }: { errand: Errand }) {
  const { t } = useTranslation()
  const [, setParams] = useSearchParams()
  const Icon = ERRAND_ICONS[e.kind]
  const recordLink = errandRecordLink(e)
  return (
    <li>
      <Card className="gap-2 py-3">
        <CardContent className="flex flex-wrap items-start gap-3 px-4">
          <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-full bg-muted"><Icon className="size-4 text-muted-foreground" /></span>
          <div className="min-w-0 flex-1 basis-56">
            <p className="flex flex-wrap items-center gap-2">
              <button type="button" className="text-start font-medium hover:underline [unicode-bidi:plaintext]"
                onClick={() => setParams((p) => { p.set('errand', String(e.id)); return p }, { replace: true })}>
                {e.title}
              </button>
              <Badge variant="outline" className={cn('font-normal', ERRAND_TONE[e.status])}>{t(`errands.status.${e.status}`)}</Badge>
            </p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {t(`errands.kinds.${e.kind}`)}{' · '}
              {recordLink ? <Link to={recordLink} className="text-primary hover:underline"><bdi>{e.place}</bdi></Link> : <bdi>{e.place}</bdi>}
              {(e.address || e.city) && <> · <span className="[unicode-bidi:plaintext]">{[e.address, e.city].filter(Boolean).join(', ')}</span></>}
            </p>
            <p className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
              <DueText errand={e} />
              <span>{e.assigned_to_name ? t('errands.by', { name: e.assigned_to_name }) : t('errands.nobodyYet')}</span>
              {e.requested_by_name && <span>{t('errands.askedBy', { name: e.requested_by_name })}</span>}
            </p>
          </div>
          <ErrandActions errand={e} />
        </CardContent>
      </Card>
    </li>
  )
}

function ErrandActions({ errand: e, onDone }: { errand: Errand; onDone?: () => void }) {
  const { t } = useTranslation()
  const refresh = useRefresh()
  const [mode, setMode] = useState<'edit' | 'finish' | 'fail' | 'cancel' | null>(null)
  const act = useMutation({
    mutationFn: async (what: 'take' | 'start') => api.post(`/errands/${e.id}/${what}/`),
    onSuccess: (_d, what) => {
      refresh()
      toast.success(t(what === 'take' ? 'errands.takenToast' : 'errands.startedToast'))
    },
    onError: (err) => toast.error(apiError(err).message),
  })
  if (!(e.can_take || e.can_progress || e.can_change)) return null
  return (
    <div className="flex flex-wrap gap-2">
      {e.can_take && <Button size="sm" disabled={act.isPending} onClick={() => act.mutate('take')}><Hand className="size-4" />{t('errands.take')}</Button>}
      {e.can_progress && e.status === 'assigned' && (
        <Button size="sm" variant="outline" disabled={act.isPending} onClick={() => act.mutate('start')}><Navigation className="size-4 rtl:-scale-x-100" />{t('errands.start')}</Button>
      )}
      {e.can_progress && (
        <>
          <Button size="sm" onClick={() => setMode('finish')}><Check className="size-4" />{t('errands.done')}</Button>
          <Button size="sm" variant="outline" onClick={() => setMode('fail')}><X className="size-4" />{t('errands.notDone')}</Button>
        </>
      )}
      {e.can_change && (
        <>
          <Button variant="ghost" size="icon-sm" onClick={() => setMode('edit')} aria-label={t('errands.editTitle')}><Pencil className="size-4" /></Button>
          <Button variant="ghost" size="icon-sm" className="text-destructive" onClick={() => setMode('cancel')} aria-label={t('errands.cancel')}><Ban className="size-4" /></Button>
        </>
      )}
      {mode === 'edit' && <ErrandDialog errand={e} onClose={() => setMode(null)} />}
      {(mode === 'finish' || mode === 'fail') && <FinishDialog errand={e} done={mode === 'finish'} onClose={() => setMode(null)} onDone={onDone} />}
      {mode === 'cancel' && <CancelDialog errand={e} onClose={() => setMode(null)} onDone={onDone} />}
    </div>
  )
}

function FinishDialog({ errand, done, onClose, onDone }: { errand: Errand; done: boolean; onClose: () => void; onDone?: () => void }) {
  const { t } = useTranslation()
  const refresh = useRefresh()
  const [note, setNote] = useState('')
  const [reference, setReference] = useState(errand.reference)
  const [files, setFiles] = useState<File[]>([])
  const picker = useRef<HTMLInputElement>(null)
  const room = MAX_ERRAND_PHOTOS - errand.photos.length
  const send = useMutation({
    mutationFn: async () => {
      const body = new FormData()
      body.append('done', String(done))
      body.append('note', note)
      body.append('reference', reference)
      files.forEach((f) => body.append('photos', f))
      return api.post(`/errands/${errand.id}/finish/`, body)
    },
    onSuccess: () => {
      refresh()
      toast.success(t(done ? 'errands.doneToast' : 'errands.failedToast'))
      onClose()
      onDone?.()
    },
    onError: (e) => toast.error(Object.values(apiError(e).fields)[0] ?? apiError(e).message),
  })
  return (
    <FormDialog open onOpenChange={(o) => !o && !send.isPending && onClose()} title={t(done ? 'errands.doneTitle' : 'errands.failTitle', { title: errand.title })}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={send.isPending}>{t('common.cancel')}</Button>
          <Button variant={done ? 'default' : 'destructive'} disabled={send.isPending || (!done && !note.trim())} onClick={() => send.mutate()}>
            {send.isPending && <Loader2 className="size-4 animate-spin" />}
            {t(done ? 'errands.markDone' : 'errands.markNotDone')}
          </Button>
        </>
      }>
      <div className="grid gap-4">
        <FormField id="ef-note" label={t(done ? 'errands.doneNote' : 'errands.failNote')}>
          <Textarea id="ef-note" value={note} dir="auto" maxLength={500} onChange={(e) => setNote(e.target.value)} className="min-h-16" />
        </FormField>
        {done && (
          <>
            <FormField id="ef-ref" label={t('errands.reference')} hint={t('errands.referenceHint')}>
              <Input id="ef-ref" value={reference} dir="ltr" maxLength={100} onChange={(e) => setReference(e.target.value)} className="font-latin" />
            </FormField>
            <div className="grid gap-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{t('errands.proof')}</span>
                <Button type="button" variant="outline" size="sm" onClick={() => picker.current?.click()} disabled={files.length >= room}>
                  <Camera className="size-4" />{t('errands.addProof')}
                </Button>
                <input ref={picker} type="file" multiple hidden accept={PHOTO_ACCEPT}
                  onChange={(ev) => {
                    const picked = Array.from(ev.target.files ?? [])
                    setFiles((f) => [...f, ...picked].slice(0, room))
                    ev.target.value = ''
                  }} />
              </div>
              {files.length > 0 && (
                <ul className="grid gap-1 text-sm">
                  {files.map((f, i) => (
                    <li key={`${i}-${f.name}`} className="flex items-center gap-2 rounded-md border border-dashed px-2.5 py-1.5">
                      <Camera className="size-3.5 shrink-0 text-muted-foreground" />
                      <bdi className="min-w-0 flex-1 truncate">{f.name}</bdi>
                      <Button variant="ghost" size="icon-xs" onClick={() => setFiles((l) => l.filter((_, j) => j !== i))} aria-label={t('visits.report.removePhoto', { name: f.name })}>
                        <X className="size-3.5" />
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-xs text-muted-foreground">{t('errands.proofHint', { n: MAX_ERRAND_PHOTOS })}</p>
            </div>
          </>
        )}
      </div>
    </FormDialog>
  )
}

function CancelDialog({ errand, onClose, onDone }: { errand: Errand; onClose: () => void; onDone?: () => void }) {
  const { t } = useTranslation()
  const refresh = useRefresh()
  const [note, setNote] = useState('')
  const send = useMutation({
    mutationFn: async () => api.post(`/errands/${errand.id}/cancel/`, { note }),
    onSuccess: () => {
      refresh()
      toast.success(t('errands.cancelledToast'))
      onClose()
      onDone?.()
    },
    onError: (e) => toast.error(apiError(e).message),
  })
  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={t('errands.cancelTitle', { title: errand.title })}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="destructive" disabled={send.isPending} onClick={() => send.mutate()}>{t('errands.cancel')}</Button>
        </>
      }>
      <FormField id="ec-note" label={t('errands.cancelNote')}>
        <Textarea id="ec-note" value={note} dir="auto" maxLength={500} onChange={(e) => setNote(e.target.value)} className="min-h-16" />
      </FormField>
    </FormDialog>
  )
}

/** One errand in full: where, when, who, what happened (each step), the reference and proof photos. */
function ErrandDetails({ id, onClose }: { id: number; onClose: () => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const { data: e, isError } = useErrand(id)
  const [open, setOpen] = useState<ErrandPhoto | null>(null)
  const recordLink = e ? errandRecordLink(e) : null
  const rows: { label: string; value: React.ReactNode }[] = e
    ? [
        { label: t('errands.kind'), value: t(`errands.kinds.${e.kind}`) },
        { label: t('errands.where'), value: recordLink ? <Link to={recordLink} className="text-primary hover:underline"><bdi>{e.place}</bdi></Link> : <bdi>{e.place}</bdi> },
        { label: t('visits.address'), value: [e.address, e.city].filter(Boolean).join(', ') },
        { label: t('visits.pinShort'), value: e.latitude && <span className="inline-flex items-center gap-1"><MapPin className="size-3.5" /><bdi dir="ltr" className="font-latin">{e.latitude}, {e.longitude}</bdi></span> },
        { label: t('errands.due'), value: <DueText errand={e} bare /> },
        { label: t('errands.runner'), value: e.assigned_to_name ?? t('errands.nobodyYet') },
        { label: t('errands.askedByLabel'), value: e.requested_by_name },
        { label: t('errands.details'), value: e.details && <span className="whitespace-pre-line [unicode-bidi:plaintext]">{e.details}</span> },
        { label: t('visits.forTask'), value: e.task && <Link to={`/tasks/${e.task.id}`} className="inline-flex items-center gap-1 text-primary hover:underline"><CheckSquare className="size-3.5" /><bdi>{e.task.title}</bdi></Link> },
        { label: t('errands.reference'), value: e.reference && <bdi dir="ltr" className="font-latin">{e.reference}</bdi> },
        { label: t('errands.history'), value: (
          <ol className="grid gap-1">
            {e.updates.map((u, i) => (
              <li key={i} className="grid">
                <span className="font-medium">{t(`errands.status.${u.status}`)}</span>
                <span className="text-xs text-muted-foreground">
                  {fmt.dateTime(u.at)}{u.by && <> · <bdi className="whitespace-nowrap">{u.by}</bdi></>}
                </span>
                {u.note && <span className="[unicode-bidi:plaintext] ltr:text-left rtl:text-right">{u.note}</span>}
              </li>
            ))}
          </ol>
        ) },
        { label: t('errands.proof'), value: e.photos.length > 0 && (
          <ul className="flex flex-wrap gap-2">{e.photos.map((p) => <Thumb key={p.id} photo={p} onOpen={() => setOpen(p)} />)}</ul>
        ) },
      ]
    : []
  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={e?.title ?? t('errands.title')}>
      {isError ? (
        <p className="text-sm text-muted-foreground">{t('errands.notFound')}</p>
      ) : !e ? (
        <Skeleton className="h-40" />
      ) : (
        <div className="grid gap-3">
          <Badge variant="outline" className={cn('w-fit font-normal', ERRAND_TONE[e.status])}>{t(`errands.status.${e.status}`)}</Badge>
          <dl className="grid gap-2 text-sm">
            {rows.filter((r) => r.value).map(({ label, value }) => (
              <div key={label} className="grid grid-cols-[7rem_1fr] gap-2">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="min-w-0 break-words">{value}</dd>
              </div>
            ))}
          </dl>
          <ErrandActions errand={e} onDone={onClose} />
        </div>
      )}
      {open && <Preview photo={open} onClose={() => setOpen(null)} />}
    </FormDialog>
  )
}

function Thumb({ photo, onOpen }: { photo: ErrandPhoto; onOpen: () => void }) {
  const { t } = useTranslation()
  const thumb = useAuthedBlobUrl(photo.thumbnail_url)
  return (
    <li>
      <button type="button" onClick={onOpen} className="block size-16 overflow-hidden rounded-md border bg-muted hover:opacity-90"
        aria-label={t('visits.report.openPhoto', { name: photo.original_name })}>
        {thumb && <img src={thumb} alt="" className="size-full object-cover" />}
      </button>
    </li>
  )
}

function Preview({ photo, onClose }: { photo: ErrandPhoto; onClose: () => void }) {
  const src = useAuthedBlobUrl(`${photo.download_url}?inline=1`)
  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={photo.original_name}>
      <div className="flex min-h-40 items-center justify-center rounded-md bg-muted">
        {src ? <img src={src} alt={photo.original_name} className="max-h-[70dvh] w-auto rounded-md object-contain" /> : <Loader2 className="size-6 animate-spin text-muted-foreground" />}
      </div>
    </FormDialog>
  )
}
