import { useMutation } from '@tanstack/react-query'
import { Copy, ExternalLink, FileText, Mail, MessageCircle, Search } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { EmptyState, FormDialog, FormField } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { apiError } from '@/lib/api'
import { rememberContactAttempt } from '@/lib/quickLog'
import {
  copyText,
  fillTemplate,
  mailtoUrl,
  recordTemplateUse,
  templateDir,
  useTemplates,
  whatsappUrl,
  type FilledTemplate,
  type MessageTemplate,
} from '@/lib/templates'
import { cn } from '@/lib/utils'
import { PlaceholderWarnings } from './TemplateEditor'

interface Recipient {
  id: number
  /** A vendor rather than a contact: its contact person and details fill the template. */
  isVendor?: boolean
  full_name: string
  company_name?: string | null
  phone?: string
  whatsapp?: string
  email?: string
}

/** "WhatsApp with template" and "Email with template" for a contact (or a vendor). */
export function TemplateSendButtons({ contact }: { contact: Recipient }) {
  const { t } = useTranslation()
  const [channel, setChannel] = useState<'whatsapp' | 'email' | null>(null)
  const wa = contact.whatsapp || contact.phone
  if (!wa && !contact.email) return null
  return (
    <>
      {wa && (
        <Button variant="outline" size="sm" onClick={() => setChannel('whatsapp')}>
          <MessageCircle className="size-3.5" />
          {t('templates.sendWhatsapp')}
        </Button>
      )}
      {contact.email && (
        <Button variant="outline" size="sm" onClick={() => setChannel('email')}>
          <Mail className="size-3.5" />
          {t('templates.sendEmail')}
        </Button>
      )}
      {channel && <SendDialog contact={contact} channel={channel} onClose={() => setChannel(null)} />}
    </>
  )
}

function SendDialog({ contact, channel, onClose }: { contact: Recipient; channel: 'whatsapp' | 'email'; onClose: () => void }) {
  const { t } = useTranslation()
  const { data: templates, isLoading } = useTemplates({ channel })
  const [query, setQuery] = useState('')
  const [chosen, setChosen] = useState<MessageTemplate | null>(null)
  const [filled, setFilled] = useState<FilledTemplate | null>(null)
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')

  const fill = useMutation({
    mutationFn: (template: MessageTemplate) => (contact.isVendor ? fillTemplate(template.id, null, contact.id) : fillTemplate(template.id, contact.id)),
    onSuccess: (result, template) => {
      setChosen(template)
      setFilled(result)
      setSubject(result.subject)
      setBody(result.body)
    },
    onError: (e) => toast.error(apiError(e).message),
  })

  const record = contact.isVendor
    ? { target: { vendor: contact.id }, name: contact.full_name, hint: contact.company_name ?? '', type: 'vendor' as const }
    : { target: { contact: contact.id }, name: contact.full_name, hint: contact.company_name ?? '', type: 'contact' as const }
  const send = () => {
    if (!chosen) return
    recordTemplateUse(chosen.id)
    // Back in the app afterwards, "Log this…" opens with what was sent.
    rememberContactAttempt(channel, record, { summary: body, subject: channel === 'email' ? subject : undefined })
    if (channel === 'whatsapp') window.open(whatsappUrl(contact.whatsapp || contact.phone || '', body), '_blank', 'noopener,noreferrer')
    else window.location.href = mailtoUrl(contact.email ?? '', subject, body)
    onClose()
  }
  const copy = async () => {
    if (!chosen) return
    const text = channel === 'email' && subject ? `${subject}\n\n${body}` : body
    if (await copyText(text)) {
      recordTemplateUse(chosen.id)
      toast.success(t('templates.copied'))
    } else {
      toast.error(t('templates.copyFailed'))
    }
  }

  const q = query.trim().toLowerCase()
  const shown = (templates ?? []).filter((tpl) => !q || `${tpl.name} ${tpl.body}`.toLowerCase().includes(q))
  const dir = templateDir(chosen?.language ?? 'en')

  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t(channel === 'whatsapp' ? 'templates.sendWhatsappTo' : 'templates.sendEmailTo', { name: contact.full_name })}
      description={chosen ? undefined : t('templates.pickToSend')}
      footer={
        chosen ? (
          <>
            <Button variant="ghost" onClick={() => (setChosen(null), setFilled(null))}>
              {t('templates.otherTemplate')}
            </Button>
            <Button variant="outline" onClick={() => void copy()}>
              <Copy className="size-4" />
              {t('templates.copy')}
            </Button>
            <Button onClick={send} disabled={!body.trim()}>
              <ExternalLink className="size-4" />
              {t(channel === 'whatsapp' ? 'templates.openWhatsapp' : 'templates.openEmail')}
            </Button>
          </>
        ) : undefined
      }
    >
      {!chosen ? (
        <div className="grid gap-2">
          <label className="flex items-center gap-2 rounded-md border bg-background px-2">
            <Search className="size-4 text-muted-foreground" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('templates.search')}
              aria-label={t('templates.search')}
              className="h-9 min-w-0 flex-1 bg-transparent text-sm outline-none"
            />
          </label>
          {isLoading ? (
            <Skeleton className="h-40" />
          ) : !shown.length ? (
            <EmptyState icon={FileText} title={t('templates.noneForChannel')} className="py-6" />
          ) : (
            <ul className="max-h-[55dvh] divide-y overflow-y-auto rounded-md border">
              {shown.map((tpl) => (
                <li key={tpl.id}>
                  <button
                    type="button"
                    disabled={fill.isPending}
                    onClick={() => fill.mutate(tpl)}
                    className="flex w-full flex-col gap-0.5 px-3 py-2 text-start hover:bg-muted"
                  >
                    <span className="flex items-center gap-2 text-sm font-medium">
                      <bdi className="min-w-0 flex-1 truncate">{tpl.name}</bdi>
                      <span className="text-[10px] text-muted-foreground uppercase font-latin">{tpl.language}</span>
                    </span>
                    <span dir={templateDir(tpl.language)} className={cn('line-clamp-2 text-xs text-muted-foreground', tpl.language === 'ur' ? 'text-right' : 'text-left')}>
                      {tpl.body}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div className="grid gap-3">
          {channel === 'email' && (
            <FormField id="send-subject" label={t('templates.subject')}>
              <Input id="send-subject" value={subject} dir={dir} onChange={(e) => setSubject(e.target.value)} />
            </FormField>
          )}
          <FormField id="send-body" label={t('templates.message')} hint={t('templates.editBeforeSending')}>
            <Textarea id="send-body" value={body} dir={dir} rows={9} className="min-h-44" onChange={(e) => setBody(e.target.value)} />
          </FormField>
          {filled && <PlaceholderWarnings filled={filled} />}
        </div>
      )}
    </FormDialog>
  )
}
