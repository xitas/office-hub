import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Braces, UserRound, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { FormDialog, FormField, SimpleSelect } from '@/components/common'
import { RecordPicker, type Picked } from '@/components/common/RecordPicker'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import {
  TEMPLATES_KEY,
  TEMPLATE_CATEGORIES,
  TEMPLATE_CHANNELS,
  TEMPLATE_LANGUAGES,
  TEMPLATE_SHARING,
  templateDir,
  usePlaceholders,
  type FilledTemplate,
  type MessageTemplate,
  type TemplateInput,
} from '@/lib/templates'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { cn } from '@/lib/utils'

const PLACEHOLDER = /\{([a-z_]+(?:\.[a-z_]+)?)\}/g

/** Create or edit a template: placeholders to insert, unknown ones flagged, and a live preview with a real contact. */
export function TemplateEditor({ template, onClose }: { template?: MessageTemplate; onClose: () => void }) {
  const { t } = useTranslation()
  const me = useMe()
  const queryClient = useQueryClient()
  const { data: placeholders } = usePlaceholders()
  const [form, setForm] = useState<TemplateInput>({
    name: template?.name ?? '',
    category: template?.category ?? 'general',
    channel: template?.channel ?? 'any',
    language: template?.language ?? (me.language === 'ur' ? 'ur' : 'en'),
    subject: template?.subject ?? '',
    body: template?.body ?? '',
    sharing: template?.sharing ?? 'personal',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [focused, setFocused] = useState<'subject' | 'body'>('body')
  const body = useRef<HTMLTextAreaElement>(null)
  const subject = useRef<HTMLInputElement>(null)
  const [contact, setContact] = useState<Picked | null>(null)
  const [picking, setPicking] = useState(false)
  const set = (key: keyof TemplateInput, value: string) => setForm((f) => ({ ...f, [key]: value }))
  const dir = templateDir(form.language)
  const hasSubject = form.channel === 'email' || form.channel === 'any'

  // Who may share how (the server checks again).
  const sharingOptions = TEMPLATE_SHARING.filter(
    (s) => s === 'personal' || me.role === 'admin' || (s === 'department' && me.role === 'manager' && !!me.department) || s === template?.sharing,
  )

  const known = new Set((placeholders ?? []).map((p) => p.key))
  const unknown = [...new Set([...`${hasSubject ? form.subject : ''}\n${form.body}`.matchAll(PLACEHOLDER)].map((m) => m[1]).filter((k) => !known.has(k)))]

  const insert = (key: string) => {
    const token = `{${key}}`
    const field = focused === 'subject' && hasSubject ? 'subject' : 'body'
    const el = field === 'subject' ? subject.current : body.current
    const value = form[field]
    const start = el?.selectionStart ?? value.length
    const end = el?.selectionEnd ?? value.length
    set(field, value.slice(0, start) + token + value.slice(end))
    requestAnimationFrame(() => {
      el?.focus()
      el?.setSelectionRange(start + token.length, start + token.length)
    })
  }

  // Debounced as a string: a new object every render would restart the timer forever.
  const previewKey = useDebouncedValue(JSON.stringify({ subject: hasSubject ? form.subject : '', body: form.body, contact }), 300)
  const previewInput = JSON.parse(previewKey) as { subject: string; body: string; contact: Picked | null }
  const preview = useQuery({
    queryKey: [...TEMPLATES_KEY, 'preview', previewInput.subject, previewInput.body, previewInput.contact?.target],
    queryFn: async () =>
      (
        await api.post<FilledTemplate>('/templates/preview/', {
          subject: previewInput.subject,
          body: previewInput.body,
          contact: previewInput.contact && 'contact' in previewInput.contact.target ? previewInput.contact.target.contact : null,
        })
      ).data,
    enabled: !!previewInput.body.trim(),
    placeholderData: (previous) => previous,
  })

  const save = useMutation({
    mutationFn: async () =>
      template
        ? (await api.patch<MessageTemplate>(`/templates/${template.id}/`, form)).data
        : (await api.post<MessageTemplate>('/templates/', form)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY })
      toast.success(template ? t('common.saved') : t('templates.created'))
      onClose()
    },
    onError: (e) => {
      const info = apiError(e)
      setErrors(info.fields)
      if (!Object.keys(info.fields).length) toast.error(info.message)
    },
  })

  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={template ? t('templates.edit') : t('templates.new')}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !form.name.trim() || !form.body.trim()}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <form
        className="grid gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <FormField id="tpl-name" label={t('templates.name')} error={errors.name}>
          <Input id="tpl-name" value={form.name} maxLength={120} dir="auto" onChange={(e) => set('name', e.target.value)} />
        </FormField>
        <div className="grid grid-cols-2 gap-3">
          <FormField id="tpl-category" label={t('templates.category')}>
            <SimpleSelect id="tpl-category" value={form.category} onChange={(v) => set('category', v)}
              options={TEMPLATE_CATEGORIES.map((c) => ({ value: c, label: t(`templates.categories.${c}`) }))} />
          </FormField>
          <FormField id="tpl-channel" label={t('templates.channel')}>
            <SimpleSelect id="tpl-channel" value={form.channel} onChange={(v) => set('channel', v)}
              options={TEMPLATE_CHANNELS.map((c) => ({ value: c, label: t(`templates.channels.${c}`) }))} />
          </FormField>
          <FormField id="tpl-language" label={t('templates.language')}>
            <SimpleSelect id="tpl-language" value={form.language} onChange={(v) => set('language', v)}
              options={TEMPLATE_LANGUAGES.map((l) => ({ value: l, label: t(`languages.${l}`) }))} />
          </FormField>
          <FormField id="tpl-sharing" label={t('templates.sharing')} error={errors.sharing}>
            <SimpleSelect id="tpl-sharing" value={form.sharing} onChange={(v) => set('sharing', v)}
              options={sharingOptions.map((s) => ({ value: s, label: t(`templates.sharingOptions.${s}`) }))} />
          </FormField>
        </div>
        {hasSubject && (
          <FormField id="tpl-subject" label={t('templates.subject')} hint={t('templates.subjectHint')}>
            <Input ref={subject} id="tpl-subject" value={form.subject} maxLength={200} dir={dir}
              onFocus={() => setFocused('subject')} onChange={(e) => set('subject', e.target.value)} />
          </FormField>
        )}
        <FormField id="tpl-body" label={t('templates.body')} error={errors.body}>
          <Textarea ref={body} id="tpl-body" value={form.body} rows={7} dir={dir} className="min-h-36"
            onFocus={() => setFocused('body')} onChange={(e) => set('body', e.target.value)} />
        </FormField>

        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <Braces className="size-3.5" />
            {t('templates.placeholders')}
          </p>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('templates.placeholders')}>
            {(placeholders ?? []).map((p) => (
              <button
                key={p.key}
                type="button"
                onClick={() => insert(p.key)}
                title={`${p.label} — ${p.example}`}
                className="rounded-md border bg-muted/50 px-1.5 py-0.5 text-xs hover:bg-muted font-latin"
                dir="ltr"
              >
                {`{${p.key}}`}
              </button>
            ))}
          </div>
        </div>

        {unknown.length > 0 && (
          <p role="alert" className="flex items-start gap-2 rounded-md bg-destructive/10 p-2 text-sm text-destructive">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <span>
              {t('templates.unknownPlaceholders')} <span className="font-latin" dir="ltr">{unknown.map((k) => `{${k}}`).join(', ')}</span>
            </span>
          </p>
        )}

        <section className="rounded-lg border bg-muted/30 p-3" aria-label={t('templates.preview')}>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h3 className="flex-1 text-sm font-medium">{t('templates.preview')}</h3>
            {contact ? (
              <span className="inline-flex items-center gap-1 rounded-md border bg-card py-0.5 ps-2 pe-0.5 text-xs">
                <UserRound className="size-3" />
                <bdi>{contact.name}</bdi>
                <Button type="button" variant="ghost" size="icon-xs" onClick={() => setContact(null)} aria-label={t('templates.clearContact')}>
                  <X className="size-3" />
                </Button>
              </span>
            ) : (
              <Button type="button" variant="outline" size="sm" onClick={() => setPicking(true)}>
                {t('templates.previewWith')}
              </Button>
            )}
          </div>
          <FilledPreview filled={preview.data} language={form.language} showSubject={hasSubject} />
        </section>
      </form>
      {picking && (
        <FormDialog open onOpenChange={(o) => !o && setPicking(false)} title={t('templates.previewWith')}>
          <RecordPicker
            idPrefix="tpl-preview"
            onPick={(p) => {
              setContact(p.type === 'contact' ? p : null)
              setPicking(false)
            }}
          />
        </FormDialog>
      )}
    </FormDialog>
  )
}

/** Filled subject and body, plus warnings for unknown and empty placeholders. */
export function FilledPreview({ filled, language, showSubject }: { filled?: FilledTemplate; language: string; showSubject?: boolean }) {
  const { t } = useTranslation()
  if (!filled) return <p className="text-sm text-muted-foreground">{t('templates.previewEmpty')}</p>
  const dir = templateDir(language)
  return (
    <div className="grid gap-2">
      {showSubject && filled.subject && (
        <p dir={dir} className={cn('text-sm font-medium', dir === 'rtl' ? 'text-right' : 'text-left')}>
          {filled.subject}
        </p>
      )}
      <p dir={dir} className={cn('text-sm whitespace-pre-wrap', dir === 'rtl' ? 'text-right' : 'text-left')}>
        {filled.body}
      </p>
      <PlaceholderWarnings filled={filled} />
    </div>
  )
}

export function PlaceholderWarnings({ filled }: { filled: FilledTemplate }) {
  const { t } = useTranslation()
  if (!filled.unknown.length && !filled.empty.length) return null
  return (
    <div className="grid gap-1 text-xs" role="alert">
      {filled.unknown.length > 0 && (
        <p className="flex items-start gap-1.5 text-destructive">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>
            {t('templates.unknownPlaceholders')} <span className="font-latin" dir="ltr">{filled.unknown.map((k) => `{${k}}`).join(', ')}</span>
          </span>
        </p>
      )}
      {filled.empty.length > 0 && (
        <p className="flex items-start gap-1.5 text-amber-700 dark:text-amber-400">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>
            {t('templates.emptyPlaceholders')} <span className="font-latin" dir="ltr">{filled.empty.map((k) => `{${k}}`).join(', ')}</span>
          </span>
        </p>
      )}
    </div>
  )
}
