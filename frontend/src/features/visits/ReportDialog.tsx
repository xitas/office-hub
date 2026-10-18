import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckSquare, ImagePlus, Loader2, LogOut, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { FormDialog, FormField, SimpleSelect } from '@/components/common'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { todayInOffice } from '@/lib/bookings'
import { CONTACT_STATUSES } from '@/lib/contacts'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { useTaskAssignees } from '@/lib/tasks'
import type { ContactStatus } from '@/lib/types'
import { useAuthedBlobUrl } from '@/lib/useAuthedBlob'
import { cn } from '@/lib/utils'
import {
  MAX_REPORT_PHOTOS, PHOTO_ACCEPT, REPORT_OUTCOMES, REPORT_TONE, VISITS_KEY, type ReportOutcome, type Visit, type VisitPhoto, type VisitReport,
} from '@/lib/visits'
import { CheckDialog } from './CheckDialog'

/**
 * Write or change a visit's report: how it went, notes, photos, the next action (it becomes a follow-up task) and,
 * on a contact's visit, the lead's status. Writing it marks a planned visit done.
 */
export function ReportDialog({ visit, onClose }: { visit: Visit; onClose: () => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const me = useMe()
  const queryClient = useQueryClient()
  const assignees = useTaskAssignees()
  const canMoveLead = usePermission('contacts.edit') && !!visit.contact && visit.record_visible
  const report = visit.report
  const today = todayInOffice(fmt.settings.timezone)
  const [outcome, setOutcome] = useState<ReportOutcome | ''>(report?.outcome ?? '')
  const [notes, setNotes] = useState(report?.notes ?? '')
  const [action, setAction] = useState(report?.next_action ?? '')
  const [actionOn, setActionOn] = useState(report?.next_action_on ?? '')
  const [assignee, setAssignee] = useState(String(me.id))
  const [status, setStatus] = useState('')
  const [reason, setReason] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [removed, setRemoved] = useState<number[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [checkingOut, setCheckingOut] = useState(false)
  const picker = useRef<HTMLInputElement>(null)
  const kept = (report?.photos ?? []).filter((p) => !removed.includes(p.id))
  const mine = visit.checks.find((c) => c.user === me.id)
  const stillIn = visit.status === 'planned' && !!mine && !mine.checked_out_at
  const makesTask = !!actionOn && !report?.follow_up_task
  const save = useMutation({
    mutationFn: async () => {
      const body = new FormData()
      body.append('outcome', outcome)
      body.append('notes', notes)
      body.append('next_action', action)
      if (actionOn) body.append('next_action_on', actionOn)
      if (makesTask && assignee !== String(me.id)) body.append('follow_up_assignee', assignee)
      if (status) {
        body.append('contact_status', status)
        body.append('status_reason', reason)
      }
      files.forEach((f) => body.append('photos', f))
      removed.forEach((id) => body.append('remove_photos', String(id)))
      return api.post(`/visits/${visit.id}/report/`, body)
    },
    onSuccess: () => {
      for (const key of [VISITS_KEY, ['timeline'], ['tasks'], ['contacts'], ['dashboard'], ['calendar']]) void queryClient.invalidateQueries({ queryKey: key })
      toast.success(t(report ? 'visits.report.savedToast' : 'visits.report.writtenToast'))
      onClose()
    },
    onError: (err) => {
      const info = apiError(err)
      setErrors(info.fields)
      toast.error(Object.values(info.fields)[0] ?? info.message)
    },
  })
  const valid = !!outcome && (!actionOn || action.trim())
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && !save.isPending && onClose()}
      title={t(report ? 'visits.report.editTitle' : 'visits.report.title', { title: visit.title })}
      description={visit.status === 'planned' ? t('visits.report.marksDone') : undefined}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={save.isPending}>{t('common.cancel')}</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !valid}>
            {save.isPending && <Loader2 className="size-4 animate-spin" />}
            {report ? t('common.save') : t('visits.report.submit')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {stillIn && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/40 p-3 text-sm">
            <span className="min-w-0 flex-1">{t('visits.report.stillIn', { time: fmt.time(mine!.checked_in_at) })}</span>
            <Button size="sm" variant="outline" onClick={() => setCheckingOut(true)}>
              <LogOut className="size-4 rtl:rotate-180" />
              {t('visits.checks.checkOut')}
            </Button>
          </div>
        )}
        <fieldset className="grid gap-2">
          <legend className="mb-2 text-sm font-medium">{t('visits.report.outcome')}</legend>
          <div className="grid grid-cols-2 gap-2">
            {REPORT_OUTCOMES.map((o) => (
              <label key={o} className={cn('flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/5 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring')}>
                <input type="radio" name="report-outcome" value={o} checked={outcome === o} onChange={() => setOutcome(o)} className="accent-primary" />
                {t(`visits.report.outcomes.${o}`)}
              </label>
            ))}
          </div>
          {errors.outcome && <p className="text-xs text-destructive">{errors.outcome}</p>}
        </fieldset>
        <FormField id="vr-notes" label={t('visits.report.notes')} error={errors.notes}>
          <Textarea id="vr-notes" value={notes} dir="auto" maxLength={4000} onChange={(e) => setNotes(e.target.value)} className="min-h-24"
            placeholder={t('visits.report.notesPlaceholder')} />
        </FormField>
        <div className="grid gap-3 sm:grid-cols-[1fr_11rem]">
          <FormField id="vr-action" label={t('visits.report.nextAction')} error={errors.next_action}>
            <Input id="vr-action" value={action} dir="auto" maxLength={200} onChange={(e) => setAction(e.target.value)} placeholder={t('visits.report.nextActionPlaceholder')} />
          </FormField>
          <FormField id="vr-action-on" label={t('visits.report.nextActionOn')} error={errors.next_action_on}>
            <Input id="vr-action-on" type="date" min={today} value={actionOn} onChange={(e) => setActionOn(e.target.value)} className="font-latin" />
          </FormField>
        </div>
        {report?.follow_up_task ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <CheckSquare className="size-3.5" />
            {t('visits.report.taskExists')}{' '}
            <Link to={`/tasks/${report.follow_up_task.id}`} className="text-primary hover:underline"><bdi>{report.follow_up_task.title}</bdi></Link>
          </p>
        ) : makesTask ? (
          <FormField id="vr-assignee" label={t('visits.report.taskFor')} error={errors.follow_up_assignee} hint={t('visits.report.taskHint')}>
            <SimpleSelect id="vr-assignee" value={assignee} onChange={setAssignee}
              options={(assignees.length ? assignees : [{ id: me.id, full_name: me.full_name }]).map((u) => ({
                value: String(u.id), label: u.id === me.id ? t('timeline.me', { name: u.full_name }) : u.full_name,
              }))} />
          </FormField>
        ) : (
          <p className="text-xs text-muted-foreground">{t('visits.report.taskHint')}</p>
        )}
        {canMoveLead && (
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField id="vr-status" label={t('visits.report.leadStatus', { name: visit.contact!.name })} error={errors.contact_status}>
              <SimpleSelect id="vr-status" value={status} onChange={setStatus}
                options={[{ value: '', label: t('visits.report.leaveStatus') }, ...CONTACT_STATUSES.map((s) => ({ value: s, label: t(`contacts.statuses.${s}`) }))]} />
            </FormField>
            {status && (
              <FormField id="vr-reason" label={t('visits.report.statusReason')}>
                <Input id="vr-reason" value={reason} dir="auto" maxLength={300} onChange={(e) => setReason(e.target.value)} />
              </FormField>
            )}
          </div>
        )}
        <div className="grid gap-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium">{t('visits.report.photos')}</span>
            <Button type="button" variant="outline" size="sm" onClick={() => picker.current?.click()} disabled={kept.length + files.length >= MAX_REPORT_PHOTOS}>
              <ImagePlus className="size-4" />
              {t('visits.report.addPhotos')}
            </Button>
            <input ref={picker} type="file" multiple hidden accept={PHOTO_ACCEPT}
              onChange={(ev) => {
                const picked = Array.from(ev.target.files ?? [])
                setFiles((f) => [...f, ...picked].slice(0, MAX_REPORT_PHOTOS - kept.length))
                ev.target.value = ''
              }} />
          </div>
          {errors.photos && <p className="text-xs text-destructive">{errors.photos}</p>}
          {kept.length + files.length > 0 && (
            <ul className="flex flex-wrap gap-2">
              {kept.map((p) => <PhotoTile key={`p${p.id}`} photo={p} onRemove={() => setRemoved((x) => [...x, p.id])} />)}
              {files.map((f, i) => <NewPhotoTile key={`f${i}-${f.name}`} file={f} onRemove={() => setFiles((list) => list.filter((_, j) => j !== i))} />)}
            </ul>
          )}
          <p className="text-xs text-muted-foreground">{t('visits.report.photosHint', { n: MAX_REPORT_PHOTOS })}</p>
        </div>
      </div>
      {checkingOut && <CheckDialog visit={visit} mode="out" onClose={() => setCheckingOut(false)} />}
    </FormDialog>
  )
}

function PhotoTile({ photo, onRemove }: { photo: VisitPhoto; onRemove: () => void }) {
  const { t } = useTranslation()
  const thumb = useAuthedBlobUrl(photo.thumbnail_url)
  return (
    <li className="relative size-20 overflow-hidden rounded-md border bg-muted">
      {thumb && <img src={thumb} alt={photo.original_name} className="size-full object-cover" />}
      <Button type="button" variant="secondary" size="icon-sm" className="absolute end-1 top-1 size-6" onClick={onRemove} aria-label={t('visits.report.removePhoto', { name: photo.original_name })}>
        <X className="size-3.5" />
      </Button>
    </li>
  )
}

function NewPhotoTile({ file, onRemove }: { file: File; onRemove: () => void }) {
  const { t } = useTranslation()
  const [src] = useState(() => URL.createObjectURL(file))
  return (
    <li className="relative size-20 overflow-hidden rounded-md border border-dashed bg-muted">
      <img src={src} alt={file.name} className="size-full object-cover" onLoad={() => URL.revokeObjectURL(src)} />
      <Button type="button" variant="secondary" size="icon-sm" className="absolute end-1 top-1 size-6" onClick={onRemove} aria-label={t('visits.report.removePhoto', { name: file.name })}>
        <X className="size-3.5" />
      </Button>
    </li>
  )
}

/** The report in a visit's details: outcome, notes, next action and its task, the lead's move, photos. */
export function ReportView({ report }: { report: VisitReport }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const [open, setOpen] = useState<VisitPhoto | null>(null)
  return (
    <div className="grid gap-1.5">
      <span className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className={cn('font-normal', REPORT_TONE[report.outcome])}>{t(`visits.report.outcomes.${report.outcome}`)}</Badge>
        {report.status_change && (
          <span className="inline-flex items-center gap-1 text-xs">
            <StatusBadge status={report.status_change.from as ContactStatus} />
            <span aria-hidden className="rtl:rotate-180">→</span>
            <StatusBadge status={report.status_change.to as ContactStatus} />
          </span>
        )}
      </span>
      {report.notes && <p className="whitespace-pre-line [unicode-bidi:plaintext]">{report.notes}</p>}
      {report.next_action && (
        <p>
          <span className="text-muted-foreground">{t('visits.report.next')} </span>
          <bdi>{report.next_action}</bdi>
          {report.next_action_on && <span className="text-muted-foreground"> · {fmt.date(`${report.next_action_on}T12:00:00`)}</span>}
        </p>
      )}
      {report.follow_up_task && (
        <Link to={`/tasks/${report.follow_up_task.id}`} className="inline-flex w-fit items-center gap-1 text-primary hover:underline">
          <CheckSquare className="size-3.5" />
          <bdi>{report.follow_up_task.title}</bdi>
          {report.follow_up_task.status === 'done' && <span className="text-xs text-muted-foreground">({t('visits.report.taskDone')})</span>}
        </Link>
      )}
      {report.photos.length > 0 && (
        <ul className="flex flex-wrap gap-2 pt-1">
          {report.photos.map((p) => <PhotoThumb key={p.id} photo={p} onOpen={() => setOpen(p)} />)}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">
        {t('visits.report.writtenBy', { name: report.written_by_name ?? '', when: fmt.dateTime(report.written_at) })}
      </p>
      {open && <PhotoPreview photo={open} onClose={() => setOpen(null)} />}
    </div>
  )
}

function PhotoThumb({ photo, onOpen }: { photo: VisitPhoto; onOpen: () => void }) {
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

function PhotoPreview({ photo, onClose }: { photo: VisitPhoto; onClose: () => void }) {
  const src = useAuthedBlobUrl(`${photo.download_url}?inline=1`)
  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={photo.original_name}>
      <div className="flex min-h-40 items-center justify-center rounded-md bg-muted">
        {src ? <img src={src} alt={photo.original_name} className="max-h-[70dvh] w-auto rounded-md object-contain" /> : <Loader2 className="size-6 animate-spin text-muted-foreground" />}
      </div>
    </FormDialog>
  )
}
