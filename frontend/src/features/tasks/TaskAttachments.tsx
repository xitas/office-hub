import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Download, File, FileArchive, FileImage, FileSpreadsheet, FileText, Loader2, Paperclip, Trash2, Upload } from 'lucide-react'
import { useRef, useState, type DragEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { FormDialog } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { api, apiError } from '@/lib/api'
import { useConfirm } from '@/lib/confirm'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { ATTACHMENT_ACCEPT, ATTACHMENT_MAX_MB, formatBytes, type TaskAttachment } from '@/lib/tasks'
import { downloadFile } from '@/lib/transfer'
import { useAuthedBlobUrl } from '@/lib/useAuthedBlob'
import { cn } from '@/lib/utils'

const KIND_ICONS = { image: FileImage, pdf: FileText, office: FileSpreadsheet, text: FileText, zip: FileArchive }

/** Files on the task itself, with an upload area. */
export function TaskAttachments({ taskId, attachments }: { taskId: number; attachments: TaskAttachment[] | undefined }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const canUpload = usePermission('tasks.edit')
  const input = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const body = new FormData()
      for (const f of files) body.append('files', f)
      return (await api.post<TaskAttachment[]>(`/tasks/${taskId}/attachments/`, body)).data
    },
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ['tasks', 'activity', taskId] })
      toast.success(t('tasks.files.uploaded', { count: saved.length }))
    },
    onError: (err) => {
      const info = apiError(err)
      toast.error(info.fields.files ?? info.message)
    },
  })

  const pick = (list: FileList | null) => {
    const files = Array.from(list ?? [])
    if (!files.length) return
    const tooBig = files.find((f) => f.size > ATTACHMENT_MAX_MB * 1024 * 1024)
    if (tooBig) return void toast.error(t('tasks.files.tooLarge', { name: tooBig.name, mb: ATTACHMENT_MAX_MB }))
    upload.mutate(files)
  }

  return (
    <Card
      onDragOver={(e: DragEvent) => {
        if (!canUpload || !e.dataTransfer.types.includes('Files')) return
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false)
      }}
      onDrop={(e) => {
        if (!canUpload) return
        e.preventDefault()
        setDragOver(false)
        pick(e.dataTransfer.files)
      }}
      className={cn(dragOver && 'ring-2 ring-primary/40')}
    >
      <CardHeader className="flex flex-row items-center gap-2">
        <Paperclip className="size-4 text-muted-foreground" />
        <CardTitle className="flex-1">{t('tasks.files.title')}</CardTitle>
        {canUpload && (
          <>
            <Button size="sm" variant="outline" onClick={() => input.current?.click()} disabled={upload.isPending}>
              {upload.isPending ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
              {t('tasks.files.upload')}
            </Button>
            <input
              ref={input}
              type="file"
              multiple
              accept={ATTACHMENT_ACCEPT}
              className="sr-only"
              aria-label={t('tasks.files.upload')}
              onChange={(e) => {
                pick(e.target.files)
                e.target.value = ''
              }}
            />
          </>
        )}
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-2">
        {attachments?.length ? (
          <AttachmentList attachments={attachments} taskId={taskId} />
        ) : (
          <p className="text-sm text-muted-foreground">{t('tasks.files.empty')}</p>
        )}
        {canUpload && <p className="text-xs text-muted-foreground">{t('tasks.files.hint', { mb: ATTACHMENT_MAX_MB })}</p>}
      </CardContent>
    </Card>
  )
}

/** Thumbnails for images, an icon with name, size, uploader and date for other files. */
export function AttachmentList({ attachments, taskId, compact }: { attachments: TaskAttachment[]; taskId: number; compact?: boolean }) {
  return (
    <ul className={cn('grid grid-cols-1 gap-2', compact && 'sm:grid-cols-2')}>
      {attachments.map((a) => (
        <li key={a.id}>
          <AttachmentRow attachment={a} taskId={taskId} />
        </li>
      ))}
    </ul>
  )
}

function AttachmentRow({ attachment: a, taskId }: { attachment: TaskAttachment; taskId: number }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const confirm = useConfirm()
  const queryClient = useQueryClient()
  const thumb = useAuthedBlobUrl(a.thumbnail_url)
  const [previewing, setPreviewing] = useState(false)
  const Icon = KIND_ICONS[a.kind] ?? File

  const remove = useMutation({
    mutationFn: () => api.delete(`/task-attachments/${a.id}/`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tasks', 'activity', taskId] })
      toast.success(t('common.deleted'))
    },
    onError: (err) => toast.error(apiError(err).message),
  })
  const download = async () => {
    try {
      await downloadFile(a.download_url, {}, a.original_name)
    } catch {
      toast.error(t('transfer.exportFailed'))
    }
  }
  const askDelete = async () => {
    const ok = await confirm({
      title: t('tasks.files.deleteTitle', { name: a.original_name }),
      description: t('tasks.files.deleteHint'),
      confirmLabel: t('common.delete'),
      destructive: true,
    })
    if (ok) remove.mutate()
  }

  return (
    <div className="flex items-center gap-3 rounded-lg border p-2">
      {a.kind === 'image' ? (
        <button
          type="button"
          onClick={() => setPreviewing(true)}
          className="size-12 shrink-0 overflow-hidden rounded-md bg-muted"
          aria-label={t('tasks.files.preview', { name: a.original_name })}
        >
          {thumb ? <img src={thumb} alt="" className="size-full object-cover" /> : <FileImage className="m-auto size-5 text-muted-foreground" />}
        </button>
      ) : (
        <span className="flex size-12 shrink-0 items-center justify-center rounded-md bg-muted">
          <Icon className="size-5 text-muted-foreground" />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium" title={a.original_name}>
          <bdi>{a.original_name}</bdi>
        </p>
        <p className="truncate text-xs text-muted-foreground">
          <span className="font-latin">{formatBytes(a.size)}</span>
          {a.uploaded_by_name && (
            <>
              {' · '}
              <bdi>{a.uploaded_by_name}</bdi>
            </>
          )}
          {' · '}
          {fmt.relative(a.created_at)}
        </p>
      </div>
      <Button variant="ghost" size="icon-sm" onClick={() => void download()} aria-label={t('tasks.files.download', { name: a.original_name })}>
        <Download className="size-4" />
      </Button>
      {a.can_delete && (
        <Button variant="ghost" size="icon-sm" onClick={() => void askDelete()} disabled={remove.isPending} aria-label={t('tasks.files.delete', { name: a.original_name })}>
          <Trash2 className="size-4" />
        </Button>
      )}
      {previewing && <ImagePreview attachment={a} onClose={() => setPreviewing(false)} />}
    </div>
  )
}

function ImagePreview({ attachment, onClose }: { attachment: TaskAttachment; onClose: () => void }) {
  const src = useAuthedBlobUrl(`${attachment.download_url}?inline=1`)
  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={attachment.original_name}>
      <div className="flex min-h-40 items-center justify-center rounded-md bg-muted">
        {src ? <img src={src} alt={attachment.original_name} className="max-h-[70dvh] w-auto rounded-md object-contain" /> : <Loader2 className="size-6 animate-spin text-muted-foreground" />}
      </div>
    </FormDialog>
  )
}
