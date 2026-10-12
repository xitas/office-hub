import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Download, FileText, Loader2, Pencil, Reply, SmilePlus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { FormDialog, UserAvatar } from '@/components/common'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { REACTIONS, replaceMessage, type ChatAttachment, type ChatMessage } from '@/lib/chat'
import { useConfirm } from '@/lib/confirm'
import { useFormat } from '@/lib/format'
import { bodyToEditable, editableToBody } from '@/lib/tasks'
import { downloadFile } from '@/lib/transfer'
import { useAuthedBlobUrl } from '@/lib/useAuthedBlob'
import { cn } from '@/lib/utils'
import { MessageText, RecordCards } from './MessageBody'
import { BIDI_TEXT, plainText } from './text'

export function MessageItem({
  message: m,
  grouped,
  canChange,
  now,
  onReply,
  onJump,
}: {
  message: ChatMessage
  grouped: boolean
  canChange: boolean
  now: number
  onReply: (m: ChatMessage) => void
  onJump: (id: number) => void
}) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const me = useMe()
  const queryClient = useQueryClient()
  const confirm = useConfirm()
  const [editing, setEditing] = useState(false)
  const mine = m.author?.id === me.id
  const editable = mine && canChange && !m.deleted && !!m.editable_until && new Date(m.editable_until).getTime() > now
  const name = m.author?.full_name ?? t('chat.someone')

  const remove = useMutation({
    mutationFn: async () => api.delete(`/chat/messages/${m.id}/`),
    onSuccess: () => replaceMessage(queryClient, { ...m, body: '', deleted: true, editable_until: null, reactions: [], attachments: [] }),
    onError: (e) => toast.error(apiError(e).message),
  })
  const react = useMutation({
    mutationFn: async (emoji: string) => (await api.post<{ message: ChatMessage }>(`/chat/messages/${m.id}/react/`, { emoji })).data.message,
    onSuccess: (updated) => replaceMessage(queryClient, updated),
    onError: (e) => toast.error(apiError(e).message),
  })

  return (
    <li
      id={`message-${m.id}`}
      tabIndex={-1}
      className={cn('group relative flex gap-2.5 rounded-md px-1 py-0.5 outline-none hover:bg-muted/40 focus-within:bg-muted/40 target:bg-primary/10', !grouped && 'mt-2')}
    >
      <div className="w-8 shrink-0">{!grouped && <UserAvatar name={name} src={m.author?.avatar} className="size-8" />}</div>
      <div className="min-w-0 flex-1">
        {grouped ? (
          <span className="sr-only">{name}</span>
        ) : (
          <p className="flex items-baseline gap-2">
            <bdi className="text-sm font-semibold">{name}</bdi>
            <time dateTime={m.created_at} className="text-[11px] text-muted-foreground font-latin" title={fmt.dateTime(m.created_at)}>
              <bdi>{fmt.time(m.created_at)}</bdi>
            </time>
          </p>
        )}
        {m.reply && (
          <button
            type="button"
            onClick={() => onJump(m.reply!.id)}
            className="mt-0.5 mb-1 flex max-w-full items-center gap-1.5 rounded-md border-s-2 border-primary/50 bg-muted/60 px-2 py-1 text-start text-xs hover:bg-muted"
            aria-label={t('chat.jumpToOriginal', { name: m.reply.author?.full_name ?? t('chat.someone') })}
          >
            <Reply className="size-3 shrink-0 text-muted-foreground rtl:-scale-x-100" />
            <bdi className="shrink-0 font-medium">{m.reply.author?.full_name ?? t('chat.someone')}</bdi>
            <span className={cn('min-w-0 truncate text-muted-foreground', BIDI_TEXT)}>{m.reply.deleted ? t('chat.deleted') : plainText(m.reply.body) || '📎'}</span>
          </button>
        )}
        {editing ? (
          <EditBox message={m} onDone={(updated) => {
            if (updated) replaceMessage(queryClient, updated)
            setEditing(false)
          }} />
        ) : m.deleted ? (
          <p className="text-sm text-muted-foreground italic">{t('chat.deleted')}</p>
        ) : (
          m.body && (
            <p className={cn('text-sm break-words whitespace-pre-wrap', BIDI_TEXT)}>
              <MessageText body={m.body} />
              {m.edited_at && <span className="ms-1.5 text-[11px] text-muted-foreground">({t('chat.edited')})</span>}
            </p>
          )
        )}
        {!m.deleted && m.body && <RecordCards body={m.body} />}
        {!m.deleted && m.attachments.length > 0 && (
          <ul className="mt-1 flex flex-wrap gap-2">
            {m.attachments.map((a) => (
              <li key={a.id}>
                <AttachmentChip attachment={a} />
              </li>
            ))}
          </ul>
        )}
        {!m.deleted && m.reactions.length > 0 && (
          <ul className="mt-1 flex flex-wrap gap-1" aria-label={t('chat.reactions')}>
            {m.reactions.map((r) => {
              const mineToo = r.users.some((u) => u.id === me.id)
              const who = r.users.map((u) => (u.id === me.id ? t('chat.you') : u.full_name)).join(', ')
              return (
                <li key={r.emoji}>
                  <button
                    type="button"
                    disabled={!canChange || react.isPending}
                    aria-pressed={mineToo}
                    onClick={() => react.mutate(r.emoji)}
                    title={who}
                    aria-label={t('chat.reactionLabel', { emoji: r.emoji, count: r.count, names: who })}
                    className={cn(
                      'flex h-6 items-center gap-1 rounded-full border px-2 text-xs transition-colors',
                      mineToo ? 'border-primary/50 bg-primary/10 text-primary' : 'bg-card hover:bg-muted',
                    )}
                  >
                    <span aria-hidden>{r.emoji}</span>
                    <span className="font-latin">{r.count}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
      {!m.deleted && !editing && canChange && (
        <div
          className="pointer-events-none absolute -top-3 end-2 flex items-center gap-0.5 rounded-md border bg-card p-0.5 opacity-0 shadow-sm transition-opacity group-focus-within:pointer-events-auto group-focus-within:opacity-100 group-hover:pointer-events-auto group-hover:opacity-100"
        >
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="ghost" size="icon-xs" aria-label={t('chat.react')} title={t('chat.react')} />}>
              <SmilePlus className="size-3.5" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="flex min-w-0 gap-0.5 p-1">
              {REACTIONS.map((emoji) => (
                <DropdownMenuItem key={emoji} onClick={() => react.mutate(emoji)} className="justify-center px-2 text-lg" aria-label={t('chat.reactWith', { emoji })}>
                  {emoji}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
          <Button variant="ghost" size="icon-xs" onClick={() => onReply(m)} aria-label={t('chat.reply')} title={t('chat.reply')}>
            <Reply className="size-3.5 rtl:-scale-x-100" />
          </Button>
          {editable && (
            <Button variant="ghost" size="icon-xs" onClick={() => setEditing(true)} aria-label={t('chat.edit')} title={t('chat.edit')}>
              <Pencil className="size-3.5" />
            </Button>
          )}
          {mine && (
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label={t('chat.delete')}
              title={t('chat.delete')}
              onClick={async () => {
                if (await confirm({ title: t('chat.deleteConfirm'), confirmLabel: t('chat.delete'), destructive: true })) remove.mutate()
              }}
            >
              <Trash2 className="size-3.5" />
            </Button>
          )}
        </div>
      )}
    </li>
  )
}

function size(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function AttachmentChip({ attachment: a }: { attachment: ChatAttachment }) {
  const { t } = useTranslation()
  const thumb = useAuthedBlobUrl(a.thumbnail_url)
  const [preview, setPreview] = useState(false)
  const download = () => void downloadFile(a.download_url, {}, a.original_name).catch(() => toast.error(t('chat.downloadFailed')))

  if (a.kind === 'image' && a.thumbnail_url) {
    return (
      <>
        <button
          type="button"
          onClick={() => setPreview(true)}
          className="block overflow-hidden rounded-md border bg-muted"
          aria-label={t('chat.openImage', { name: a.original_name })}
        >
          {thumb ? (
            <img src={thumb} alt={a.original_name} className="max-h-48 max-w-64 object-cover" />
          ) : (
            <span className="flex size-32 items-center justify-center">
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            </span>
          )}
        </button>
        {preview && <ImagePreview attachment={a} onClose={() => setPreview(false)} onDownload={download} />}
      </>
    )
  }
  return (
    <button
      type="button"
      onClick={download}
      className="flex max-w-64 items-center gap-2 rounded-md border bg-card px-2.5 py-1.5 text-start text-sm hover:bg-muted"
      aria-label={t('chat.downloadFile', { name: a.original_name })}
    >
      <FileText className="size-4 shrink-0 text-muted-foreground" />
      <span className="min-w-0">
        <bdi className="block truncate">{a.original_name}</bdi>
        <span className="block text-[11px] text-muted-foreground font-latin">{size(a.size)}</span>
      </span>
      <Download className="size-3.5 shrink-0 text-muted-foreground" />
    </button>
  )
}

function ImagePreview({ attachment, onClose, onDownload }: { attachment: ChatAttachment; onClose: () => void; onDownload: () => void }) {
  const { t } = useTranslation()
  const src = useAuthedBlobUrl(`${attachment.download_url}?inline=1`)
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={attachment.original_name}
      footer={
        <Button variant="outline" onClick={onDownload}>
          <Download className="size-4" />
          {t('chat.download')}
        </Button>
      }
    >
      <div className="flex min-h-40 items-center justify-center rounded-md bg-muted">
        {src ? <img src={src} alt={attachment.original_name} className="max-h-[70dvh] w-auto rounded-md object-contain" /> : <Loader2 className="size-6 animate-spin text-muted-foreground" />}
      </div>
    </FormDialog>
  )
}

function EditBox({ message, onDone }: { message: ChatMessage; onDone: (updated?: ChatMessage) => void }) {
  const { t } = useTranslation()
  // Mentions read as "@Full Name" while editing and turn back into mentions when saved.
  const [original] = useState(() => bodyToEditable(message.body))
  const [body, setBody] = useState(original.text)
  const save = useMutation({
    mutationFn: async () =>
      (await api.patch<ChatMessage>(`/chat/messages/${message.id}/`, { body: editableToBody(body, original.mentions) })).data,
    onSuccess: (updated) => onDone(updated),
    onError: (e) => toast.error(apiError(e).message),
  })
  return (
    <div className="mt-1 space-y-2">
      <Textarea
        value={body}
        dir="auto"
        autoFocus
        maxLength={4000}
        aria-label={t('chat.edit')}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onDone()
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            if (body.trim()) save.mutate()
          }
        }}
        className="min-h-16"
      />
      <div className="flex gap-2">
        <Button size="sm" onClick={() => save.mutate()} disabled={!body.trim() || save.isPending}>
          {t('common.save')}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onDone()}>
          {t('common.cancel')}
        </Button>
      </div>
    </div>
  )
}
