import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRightLeft,
  CalendarClock,
  CircleCheck,
  CirclePlus,
  Flag,
  History,
  ListChecks,
  MoreHorizontal,
  Paperclip,
  Pencil,
  Send,
  Trash2,
  Type,
  Users,
  X,
  type LucideIcon,
} from 'lucide-react'
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { UserAvatar } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { api, apiError } from '@/lib/api'
import { useConfirm } from '@/lib/confirm'
import { useFormat } from '@/lib/format'
import {
  ATTACHMENT_ACCEPT,
  ATTACHMENT_MAX_MB,
  bodyToEditable,
  editableToBody,
  formatBytes,
  MENTION_RE,
  type MentionPerson,
  type TaskActivityItem,
  type TaskComment,
} from '@/lib/tasks'
import { AttachmentList } from './TaskAttachments'
import { MentionTextarea } from './MentionTextarea'

const EVENT_ICONS: Record<string, LucideIcon> = {
  created: CirclePlus,
  status: ArrowRightLeft,
  priority: Flag,
  title: Type,
  due: CalendarClock,
  assignees: Users,
  checklist_added: ListChecks,
  checklist_done: CircleCheck,
  checklist_undone: ListChecks,
  checklist_renamed: ListChecks,
  checklist_removed: ListChecks,
  attachment_added: Paperclip,
  attachment_removed: Paperclip,
}

/** Comments and changes in one timeline, oldest first, with the comment box at the end. */
export function TaskActivity({ taskId, items, loading }: { taskId: number; items: TaskActivityItem[] | undefined; loading: boolean }) {
  const { t } = useTranslation()

  // Notification links point at #comment-<id>: bring that comment into view once it's loaded.
  useEffect(() => {
    if (!items || !window.location.hash.startsWith('#comment-')) return
    document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ block: 'center' })
  }, [items])

  return (
    <Card>
      <CardHeader className="flex flex-row items-center gap-2">
        <History className="size-4 text-muted-foreground" />
        <CardTitle>{t('tasks.activity.title')}</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4">
        {loading || !items ? (
          <Skeleton className="h-24" />
        ) : (
          <ol className="grid grid-cols-1 gap-3">
            {items.map((item) =>
              item.type === 'comment' ? (
                <li key={item.id} id={item.id} className="scroll-mt-24">
                  <CommentItem taskId={taskId} comment={item.comment} />
                </li>
              ) : (
                <li key={item.id}>
                  <EventItem item={item} />
                </li>
              ),
            )}
          </ol>
        )}
        <CommentComposer taskId={taskId} />
      </CardContent>
    </Card>
  )
}

function EventItem({ item }: { item: Extract<TaskActivityItem, { type: 'event' }> }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const Icon = EVENT_ICONS[item.kind] ?? History
  const d = item.data as Record<string, string | string[] | null>
  const day = (v: unknown) => (v ? fmt.date(`${v as string}T12:00:00`) : '')
  const values: Record<string, string> = { actor: item.actor_name ?? t('admin.audit.system') }
  let key = `tasks.activity.events.${item.kind}`
  switch (item.kind) {
    case 'status':
      values.old = t(`tasks.statuses.${d.old}`)
      values.new = t(`tasks.statuses.${d.new}`)
      break
    case 'priority':
      values.old = t(`tasks.priorities.${d.old}`)
      values.new = t(`tasks.priorities.${d.new}`)
      break
    case 'title':
      values.new = String(d.new)
      break
    case 'due':
      values.old = [day(d.old), d.old_time].filter(Boolean).join(' ')
      values.new = [day(d.new), d.new_time].filter(Boolean).join(' ')
      key = d.new ? (d.old ? key : `${key}Set`) : `${key}Removed`
      break
    case 'assignees': {
      const added = (d.added as string[]) ?? []
      const removed = (d.removed as string[]) ?? []
      values.added = added.join(t('tasks.activity.listSeparator'))
      values.removed = removed.join(t('tasks.activity.listSeparator'))
      key = added.length && removed.length ? `${key}Both` : added.length ? `${key}Added` : `${key}Removed`
      break
    }
    default:
      values.text = String(d.text ?? d.name ?? '')
      values.old = String(d.old ?? '')
  }
  return (
    <div className="flex items-start gap-3 text-sm">
      <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Icon className="size-3.5" />
      </span>
      <p className="min-w-0 flex-1 pt-1 text-muted-foreground">
        <Trans i18nKey={key} values={values} components={{ b: <bdi className="font-medium text-foreground" />, q: <bdi className="text-foreground" /> }} />
        <span className="whitespace-nowrap">
          {' · '}
          <time dateTime={item.created_at} title={fmt.dateTime(item.created_at)}>
            {fmt.relative(item.created_at)}
          </time>
        </span>
      </p>
    </div>
  )
}

/** Comment text with @mentions shown as chips. */
function CommentBody({ body }: { body: string }) {
  const parts: ReactNode[] = []
  let last = 0
  for (const m of body.matchAll(MENTION_RE)) {
    parts.push(body.slice(last, m.index))
    parts.push(
      <bdi key={m.index} className="rounded bg-primary/10 px-1 font-medium text-primary">
        @{m[1]}
      </bdi>,
    )
    last = (m.index ?? 0) + m[0].length
  }
  parts.push(body.slice(last))
  return (
    <p dir="auto" className="text-sm whitespace-pre-wrap break-words">
      {parts.map((p, i) => (
        <Fragment key={i}>{p}</Fragment>
      ))}
    </p>
  )
}

function CommentItem({ taskId, comment }: { taskId: number; comment: TaskComment }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const confirm = useConfirm()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(() => bodyToEditable(comment.body))
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['tasks', 'activity', taskId] })
    void queryClient.invalidateQueries({ queryKey: ['tasks', 'list'] })
  }

  const save = useMutation({
    mutationFn: () => api.patch(`/tasks/${taskId}/comments/${comment.id}/`, { body: editableToBody(draft.text.trim(), draft.mentions) }),
    onSuccess: () => {
      setEditing(false)
      refresh()
    },
    onError: (err) => toast.error(apiError(err).message),
  })
  const remove = useMutation({
    mutationFn: () => api.delete(`/tasks/${taskId}/comments/${comment.id}/`),
    onSuccess: () => {
      refresh()
      toast.success(t('common.deleted'))
    },
    onError: (err) => toast.error(apiError(err).message),
  })
  const askDelete = async () => {
    const ok = await confirm({
      title: t('tasks.comments.deleteTitle'),
      description: comment.attachments.length ? t('tasks.comments.deleteHintFiles') : t('tasks.comments.deleteHint'),
      confirmLabel: t('common.delete'),
      destructive: true,
    })
    if (ok) remove.mutate()
  }

  return (
    <div className="flex items-start gap-3">
      <UserAvatar name={comment.author_name ?? '?'} src={comment.author_avatar} className="size-8" />
      <div className="min-w-0 flex-1 rounded-lg border bg-muted/30 px-3 py-2">
        <div className="flex items-center gap-2">
          <p className="min-w-0 flex-1 truncate text-sm">
            <bdi className="font-medium">{comment.author_name ?? t('admin.audit.system')}</bdi>
            <span className="text-xs text-muted-foreground">
              {' · '}
              <time dateTime={comment.created_at} title={fmt.dateTime(comment.created_at)}>
                {fmt.relative(comment.created_at)}
              </time>
              {comment.edited_at && <span title={fmt.dateTime(comment.edited_at)}> · {t('tasks.comments.edited')}</span>}
            </span>
          </p>
          {(comment.can_edit || comment.can_delete) && !editing && (
            <DropdownMenu>
              <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" className="-me-1.5" aria-label={t('tasks.comments.actions')} />}>
                <MoreHorizontal className="size-4" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {comment.can_edit && (
                  <DropdownMenuItem
                    onClick={() => {
                      setDraft(bodyToEditable(comment.body))
                      setEditing(true)
                    }}
                  >
                    <Pencil className="size-4" />
                    {t('common.edit')}
                  </DropdownMenuItem>
                )}
                {comment.can_delete && (
                  <DropdownMenuItem variant="destructive" onClick={() => void askDelete()}>
                    <Trash2 className="size-4" />
                    {t('common.delete')}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
        {editing ? (
          <div className="mt-2 grid grid-cols-1 gap-2">
            <MentionTextarea
              id={`edit-comment-${comment.id}`}
              taskId={taskId}
              value={draft.text}
              onChange={(text) => setDraft((d) => ({ ...d, text }))}
              mentions={draft.mentions}
              onMentionsChange={(mentions) => setDraft((d) => ({ ...d, mentions }))}
              onSubmitShortcut={() => save.mutate()}
              autoFocus
            />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                {t('common.cancel')}
              </Button>
              <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
                {t('common.save')}
              </Button>
            </div>
          </div>
        ) : (
          comment.body && (
            <div className="mt-1">
              <CommentBody body={comment.body} />
            </div>
          )
        )}
        {comment.attachments.length > 0 && (
          <div className="mt-2">
            <AttachmentList attachments={comment.attachments} taskId={taskId} compact />
          </div>
        )}
      </div>
    </div>
  )
}

function CommentComposer({ taskId }: { taskId: number }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [text, setText] = useState('')
  const [mentions, setMentions] = useState<MentionPerson[]>([])
  const [files, setFiles] = useState<File[]>([])

  const send = useMutation({
    mutationFn: async () => {
      const body = editableToBody(text.trim(), mentions)
      if (!files.length) return (await api.post<TaskComment>(`/tasks/${taskId}/comments/`, { body })).data
      const form = new FormData()
      form.append('body', body)
      for (const f of files) form.append('files', f)
      return (await api.post<TaskComment>(`/tasks/${taskId}/comments/`, form)).data
    },
    onSuccess: () => {
      setText('')
      setMentions([])
      setFiles([])
      void queryClient.invalidateQueries({ queryKey: ['tasks', 'activity', taskId] })
      void queryClient.invalidateQueries({ queryKey: ['tasks', 'list'] })
    },
    onError: (err) => {
      const info = apiError(err)
      toast.error(info.fields.files ?? info.fields.body ?? info.message)
    },
  })
  const canSend = (text.trim() !== '' || files.length > 0) && !send.isPending

  const addFiles = (list: FileList | null) => {
    const picked = Array.from(list ?? [])
    const tooBig = picked.find((f) => f.size > ATTACHMENT_MAX_MB * 1024 * 1024)
    if (tooBig) return void toast.error(t('tasks.files.tooLarge', { name: tooBig.name, mb: ATTACHMENT_MAX_MB }))
    setFiles((f) => [...f, ...picked].slice(0, 10))
  }

  return (
    <div className="grid grid-cols-1 gap-2 border-t pt-4">
      <label htmlFor="new-comment" className="sr-only">
        {t('tasks.comments.write')}
      </label>
      <MentionTextarea
        id="new-comment"
        taskId={taskId}
        value={text}
        onChange={setText}
        mentions={mentions}
        onMentionsChange={setMentions}
        placeholder={t('tasks.comments.placeholder')}
        onSubmitShortcut={() => canSend && send.mutate()}
      />
      {files.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="inline-flex items-center gap-1.5 rounded-full border bg-muted/40 py-0.5 ps-2.5 pe-1 text-xs">
              <Paperclip className="size-3" />
              <bdi className="max-w-48 truncate">{f.name}</bdi>
              <span className="text-muted-foreground font-latin">{formatBytes(f.size)}</span>
              <button
                type="button"
                className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                onClick={() => setFiles((all) => all.filter((_, j) => j !== i))}
                aria-label={t('tasks.files.remove', { name: f.name })}
              >
                <X className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-center justify-between gap-2">
        <div>
          <Button type="button" variant="ghost" size="sm" onClick={() => input.current?.click()}>
            <Paperclip className="size-4" />
            {t('tasks.comments.attach')}
          </Button>
          <input
            ref={input}
            type="file"
            multiple
            accept={ATTACHMENT_ACCEPT}
            className="sr-only"
            aria-label={t('tasks.comments.attach')}
            onChange={(e) => {
              addFiles(e.target.files)
              e.target.value = ''
            }}
          />
        </div>
        <Button onClick={() => send.mutate()} disabled={!canSend}>
          <Send className="size-4 rtl:-scale-x-100" />
          {t('tasks.comments.send')}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{t('tasks.comments.hint')}</p>
    </div>
  )
}
