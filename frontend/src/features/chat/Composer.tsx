import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileText, Paperclip, Reply, SendHorizontal, X } from 'lucide-react'
import { forwardRef, useEffect, useImperativeHandle, useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { CONVERSATIONS_KEY, MAX_FILES, MAX_MESSAGE, addMessage, getDraft, setDraft, type ChatMessage } from '@/lib/chat'
import { sendRealtime } from '@/lib/ws'
import { cn } from '@/lib/utils'
import { BIDI_TEXT } from './text'

const MAX_BYTES = 10 * 1024 * 1024
const ACCEPT = '.pdf,.png,.jpg,.jpeg,.gif,.webp,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.zip'
const COUNTER_FROM = MAX_MESSAGE - 500 // the counter appears near the limit
const TYPING_EVERY = 3000

export interface ComposerHandle {
  addFiles: (files: File[]) => void
  focus: () => void
}

/** Enter sends, Shift+Enter adds a line. The draft is kept per conversation while switching. */
export const Composer = forwardRef<ComposerHandle, {
  conversationId: number
  placeholder: string
  replyTo: ChatMessage | null
  onCancelReply: () => void
}>(function Composer({ conversationId, placeholder, replyTo, onCancelReply }, ref) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [body, setBody] = useState(() => getDraft(conversationId))
  const [files, setFiles] = useState<File[]>([])
  const input = useRef<HTMLTextAreaElement>(null)
  const picker = useRef<HTMLInputElement>(null)
  const lastTyping = useRef(0)

  const addFiles = (incoming: File[]) => {
    const tooBig = incoming.filter((f) => f.size > MAX_BYTES)
    if (tooBig.length) toast.error(t('chat.fileTooBig', { name: tooBig[0].name }))
    setFiles((current) => {
      const next = [...current, ...incoming.filter((f) => f.size <= MAX_BYTES)]
      if (next.length > MAX_FILES) toast.error(t('chat.tooManyFiles', { count: MAX_FILES }))
      return next.slice(0, MAX_FILES)
    })
    input.current?.focus()
  }
  useImperativeHandle(ref, () => ({ addFiles, focus: () => input.current?.focus() }))

  useEffect(() => {
    if (replyTo) input.current?.focus()
  }, [replyTo])

  const send = useMutation({
    mutationFn: async () => {
      const url = `/chat/conversations/${conversationId}/messages/`
      if (!files.length) return (await api.post<ChatMessage>(url, { body, reply_to: replyTo?.id ?? null })).data
      const form = new FormData()
      form.append('body', body)
      if (replyTo) form.append('reply_to', String(replyTo.id))
      files.forEach((f) => form.append('files', f, f.name || 'pasted-image.png'))
      return (await api.post<ChatMessage>(url, form)).data
    },
    onSuccess: (message) => {
      setBody('')
      setDraft(conversationId, '')
      setFiles([])
      onCancelReply()
      addMessage(queryClient, message) // shown at once; the live echo of the same message is ignored
      void queryClient.invalidateQueries({ queryKey: [...CONVERSATIONS_KEY, 'mine'] })
    },
    onError: (e) => {
      const info = apiError(e)
      toast.error(info.fields.files ?? info.fields.body ?? info.message)
    },
  })

  const canSend = (body.trim().length > 0 || files.length > 0) && body.length <= MAX_MESSAGE && !send.isPending
  const submit = () => canSend && send.mutate()
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    } else if (e.key === 'Escape' && replyTo) {
      onCancelReply()
    }
  }
  const onChange = (text: string) => {
    setBody(text)
    setDraft(conversationId, text)
    const now = Date.now()
    if (text && now - lastTyping.current > TYPING_EVERY) {
      lastTyping.current = now
      sendRealtime({ type: 'chat.typing', conversation: conversationId })
    }
  }
  const left = MAX_MESSAGE - body.length

  return (
    <form
      className="border-t p-3"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      {replyTo && (
        <div className="mb-2 flex items-center gap-2 rounded-md bg-muted px-2.5 py-1.5 text-xs">
          <Reply className="size-3.5 shrink-0 text-muted-foreground rtl:-scale-x-100" />
          <span className="min-w-0 flex-1 truncate">
            {t('chat.replyingTo')} <bdi className="font-medium">{replyTo.author?.full_name ?? t('chat.someone')}</bdi>
            <span className={cn('ms-1.5 text-muted-foreground', BIDI_TEXT)}>{replyTo.body.slice(0, 80) || '📎'}</span>
          </span>
          <Button type="button" variant="ghost" size="icon-xs" onClick={onCancelReply} aria-label={t('chat.cancelReply')}>
            <X className="size-3.5" />
          </Button>
        </div>
      )}
      {files.length > 0 && (
        <ul className="mb-2 flex flex-wrap gap-2" aria-label={t('chat.filesToSend')}>
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex max-w-56 items-center gap-1.5 rounded-md border bg-card py-1 ps-2 pe-1 text-xs">
              <FileText className="size-3.5 shrink-0 text-muted-foreground" />
              <bdi className="min-w-0 truncate">{f.name || t('chat.pastedImage')}</bdi>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                onClick={() => setFiles((cur) => cur.filter((_, j) => j !== i))}
                aria-label={t('chat.removeFile', { name: f.name || t('chat.pastedImage') })}
              >
                <X className="size-3" />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-end gap-2">
        <input
          ref={picker}
          type="file"
          multiple
          accept={ACCEPT}
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(e) => {
            addFiles(Array.from(e.target.files ?? []))
            e.target.value = ''
          }}
        />
        <Button type="button" variant="ghost" size="icon" onClick={() => picker.current?.click()} aria-label={t('chat.attach')} title={t('chat.attach')}>
          <Paperclip className="size-4" />
        </Button>
        <Textarea
          ref={input}
          value={body}
          dir="auto"
          rows={1}
          placeholder={placeholder}
          aria-label={t('chat.message')}
          aria-describedby={left < MAX_MESSAGE - COUNTER_FROM ? `counter-${conversationId}` : undefined}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          onPaste={(e) => {
            const pasted = Array.from(e.clipboardData.files).filter((f) => f.type.startsWith('image/'))
            if (pasted.length) {
              e.preventDefault()
              addFiles(pasted)
            }
          }}
          className="max-h-40 min-h-10 resize-none"
        />
        <Button type="submit" size="icon" disabled={!canSend} aria-label={t('chat.send')} title={t('chat.send')}>
          <SendHorizontal className="size-4 rtl:rotate-180" />
        </Button>
      </div>
      {body.length > COUNTER_FROM && (
        <p id={`counter-${conversationId}`} className={cn('mt-1 text-end text-xs font-latin', left < 0 ? 'text-destructive' : 'text-muted-foreground')} aria-live="polite">
          {left < 0 ? t('chat.overLimit', { count: -left }) : t('chat.charsLeft', { count: left })}
        </p>
      )}
    </form>
  )
})
