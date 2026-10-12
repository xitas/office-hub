import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AtSign, FileText, Megaphone, Paperclip, Reply, SendHorizontal, X } from 'lucide-react'
import { forwardRef, useEffect, useImperativeHandle, useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { UserAvatar } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import {
  BROADCAST_CONFIRM_ABOVE,
  BROADCAST_RE,
  CONVERSATIONS_KEY,
  MAX_FILES,
  MAX_MESSAGE,
  addMessage,
  getDraft,
  setDraft,
  type ChatMessage,
  type ChatPerson,
  type Conversation,
  type MentionSuggestions,
} from '@/lib/chat'
import { useConfirm } from '@/lib/confirm'
import { editableToBody } from '@/lib/tasks'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { cn } from '@/lib/utils'
import { sendRealtime } from '@/lib/ws'
import { BIDI_TEXT, plainText } from './text'

const MAX_BYTES = 10 * 1024 * 1024
const ACCEPT = '.pdf,.png,.jpg,.jpeg,.gif,.webp,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.zip'
const COUNTER_FROM = MAX_MESSAGE - 500 // the counter appears near the limit
const TYPING_EVERY = 3000
/** "@" followed by a few letters just before the caret. */
const TRIGGER = /(^|\s)@([^\s@]{0,30})$/

type Option = { kind: 'person'; person: ChatPerson } | { kind: 'channel' | 'here' }

export interface ComposerHandle {
  addFiles: (files: File[]) => void
  focus: () => void
}

/** Enter sends, Shift+Enter adds a line, "@" suggests people. The draft is kept per conversation while switching. */
export const Composer = forwardRef<ComposerHandle, {
  conversation: Conversation
  placeholder: string
  replyTo: ChatMessage | null
  onCancelReply: () => void
}>(function Composer({ conversation, placeholder, replyTo, onCancelReply }, ref) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const confirm = useConfirm()
  const conversationId = conversation.id
  const [draft, setDraftState] = useState(() => getDraft(conversationId))
  const body = draft.text
  const [files, setFiles] = useState<File[]>([])
  const input = useRef<HTMLTextAreaElement>(null)
  const picker = useRef<HTMLInputElement>(null)
  const lastTyping = useRef(0)

  // ------------------------------------------------------------ @ suggestions
  const [query, setQuery] = useState<string | null>(null)
  const [active, setActive] = useState(0)
  const q = useDebouncedValue(query ?? '', 150)
  const { data: suggested } = useQuery({
    queryKey: ['chat', 'people', conversationId, q],
    queryFn: async () => (await api.get<MentionSuggestions>(`/chat/conversations/${conversationId}/people/`, { params: { q: q || undefined } })).data,
    enabled: query !== null,
    staleTime: 60_000,
  })
  const options: Option[] = [
    ...(suggested?.people ?? []).map((person) => ({ kind: 'person' as const, person })),
    ...(suggested?.can_broadcast
      ? (['channel', 'here'] as const).filter((k) => k.startsWith((query ?? '').toLowerCase())).map((kind) => ({ kind }))
      : []),
  ]
  const open = query !== null && options.length > 0

  const update = (text: string, mentions = draft.mentions) => {
    const next = { text, mentions }
    setDraftState(next)
    setDraft(conversationId, next)
  }
  const detect = (text: string, caret: number) => {
    const match = TRIGGER.exec(text.slice(0, caret))
    setQuery(match ? match[2] : null)
    setActive(0)
  }
  const choose = (option: Option) => {
    const el = input.current
    if (!el) return
    const caret = el.selectionStart
    const label = option.kind === 'person' ? option.person.full_name : option.kind
    const before = body.slice(0, caret).replace(/@([^\s@]{0,30})$/, `@${label} `)
    const mentions =
      option.kind === 'person' && !draft.mentions.some((m) => m.id === option.person.id) ? [...draft.mentions, option.person] : draft.mentions
    update(before + body.slice(caret), mentions)
    setQuery(null)
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(before.length, before.length)
    })
  }

  // ------------------------------------------------------------ files
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

  // ------------------------------------------------------------ sending
  const send = useMutation({
    mutationFn: async (confirmBroadcast: boolean) => {
      const url = `/chat/conversations/${conversationId}/messages/`
      const text = editableToBody(body, draft.mentions)
      if (!files.length) {
        return (await api.post<ChatMessage>(url, { body: text, reply_to: replyTo?.id ?? null, confirm_broadcast: confirmBroadcast })).data
      }
      const form = new FormData()
      form.append('body', text)
      if (replyTo) form.append('reply_to', String(replyTo.id))
      if (confirmBroadcast) form.append('confirm_broadcast', 'true')
      files.forEach((f) => form.append('files', f, f.name || 'pasted-image.png'))
      return (await api.post<ChatMessage>(url, form)).data
    },
    onSuccess: (message) => {
      update('', [])
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
  const submit = async () => {
    if (!canSend) return
    // @channel / @here in a big channel: say how many people will be notified, and ask first.
    const broadcast = conversation.kind === 'channel' && BROADCAST_RE.test(body)
    if (broadcast && conversation.member_count > BROADCAST_CONFIRM_ABOVE) {
      const ok = await confirm({
        title: t('chat.broadcastTitle'),
        description: t('chat.broadcastConfirm', { count: conversation.member_count }),
        confirmLabel: t('chat.broadcastSend'),
      })
      if (!ok) return
      send.mutate(true)
      return
    }
    send.mutate(false)
  }
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (open) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        setActive((a) => (a + (e.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        choose(options[active])
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setQuery(null)
        return
      }
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void submit()
    } else if (e.key === 'Escape' && replyTo) {
      onCancelReply()
    }
  }
  const onChange = (text: string, caret: number) => {
    update(text)
    detect(text, caret)
    const now = Date.now()
    if (text && now - lastTyping.current > TYPING_EVERY) {
      lastTyping.current = now
      sendRealtime({ type: 'chat.typing', conversation: conversationId })
    }
  }
  const left = MAX_MESSAGE - body.length
  const listId = `mention-options-${conversationId}`

  return (
    <form
      className="border-t p-3"
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
    >
      {replyTo && (
        <div className="mb-2 flex items-center gap-2 rounded-md bg-muted px-2.5 py-1.5 text-xs">
          <Reply className="size-3.5 shrink-0 text-muted-foreground rtl:-scale-x-100" />
          <span className="min-w-0 flex-1 truncate">
            {t('chat.replyingTo')} <bdi className="font-medium">{replyTo.author?.full_name ?? t('chat.someone')}</bdi>
            <span className={cn('ms-1.5 text-muted-foreground', BIDI_TEXT)}>{plainText(replyTo.body).slice(0, 80) || '📎'}</span>
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
      <div className="relative flex items-end gap-2">
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
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open ? `${listId}-${active}` : undefined}
          aria-describedby={left < MAX_MESSAGE - COUNTER_FROM ? `counter-${conversationId}` : undefined}
          onChange={(e) => onChange(e.target.value, e.target.selectionStart)}
          onKeyDown={onKeyDown}
          onBlur={() => window.setTimeout(() => setQuery(null), 150)}
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
        {open && (
          <ul
            id={listId}
            role="listbox"
            aria-label={t('chat.mentionSomeone')}
            className="absolute start-10 bottom-full z-20 mb-1 max-h-60 w-72 overflow-y-auto rounded-lg border bg-popover p-1 text-sm shadow-md"
          >
            {options.map((o, i) => (
              <li key={o.kind === 'person' ? o.person.id : o.kind} id={`${listId}-${i}`} role="option" aria-selected={i === active}>
                <button
                  type="button"
                  tabIndex={-1}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choose(o)}
                  className={cn('flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-start', i === active ? 'bg-muted' : 'hover:bg-muted')}
                >
                  {o.kind === 'person' ? (
                    <>
                      <UserAvatar name={o.person.full_name} src={o.person.avatar} className="size-6" />
                      <bdi className="truncate">{o.person.full_name}</bdi>
                    </>
                  ) : (
                    <>
                      <span className="flex size-6 items-center justify-center rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-400">
                        {o.kind === 'channel' ? <Megaphone className="size-3.5" /> : <AtSign className="size-3.5" />}
                      </span>
                      <span className="min-w-0">
                        <span className="block font-medium font-latin">@{o.kind}</span>
                        <span className="block truncate text-xs text-muted-foreground">{t(`chat.broadcast.${o.kind}`)}</span>
                      </span>
                    </>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {body.length > COUNTER_FROM && (
        <p id={`counter-${conversationId}`} className={cn('mt-1 text-end text-xs font-latin', left < 0 ? 'text-destructive' : 'text-muted-foreground')} aria-live="polite">
          {left < 0 ? t('chat.overLimit', { count: -left }) : t('chat.charsLeft', { count: left })}
        </p>
      )}
    </form>
  )
})
