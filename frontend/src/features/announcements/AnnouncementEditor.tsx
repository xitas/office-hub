import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bold, Eye, Link2, List, ListOrdered, Paperclip, Pencil, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { FormDialog, FormField, SimpleSelect } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { ANNOUNCEMENTS_KEY, textDir, type Announcement, type AnnouncementAudience } from '@/lib/announcements'
import { api, apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { useDepartments } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { AnnouncementBody } from './AnnouncementBody'

const MAX_FILES = 10

function localToday() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Post or edit an announcement. Admins choose everyone or departments; managers post to their own department. */
export function AnnouncementEditor({ announcement, onClose }: { announcement?: Announcement; onClose: () => void }) {
  const { t } = useTranslation()
  const me = useMe()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isAdmin = me.role === 'admin'
  const { data: departments } = useDepartments()
  const [title, setTitle] = useState(announcement?.title ?? '')
  const [body, setBody] = useState(announcement?.body ?? '')
  const [audience, setAudience] = useState<AnnouncementAudience>(announcement?.audience ?? (isAdmin ? 'everyone' : 'departments'))
  const [chosen, setChosen] = useState<number[]>(announcement?.departments ?? (isAdmin || !me.department ? [] : [me.department]))
  const [pinned, setPinned] = useState(announcement?.pinned ?? false)
  const [expires, setExpires] = useState(announcement?.expires_on ?? '')
  const [files, setFiles] = useState<File[]>([])
  const [removed, setRemoved] = useState<number[]>([])
  const [preview, setPreview] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const text = useRef<HTMLTextAreaElement>(null)
  const picker = useRef<HTMLInputElement>(null)
  const kept = (announcement?.attachments ?? []).filter((a) => !removed.includes(a.id))

  const save = useMutation({
    mutationFn: async () => {
      const form = new FormData()
      form.append('title', title)
      form.append('body', body)
      form.append('audience', audience)
      if (audience === 'departments') chosen.forEach((d) => form.append('departments', String(d)))
      form.append('pinned', String(pinned))
      form.append('expires_on', expires)
      files.forEach((f) => form.append('files', f))
      removed.forEach((id) => form.append('remove_attachments', String(id)))
      return announcement
        ? (await api.patch<Announcement>(`/announcements/${announcement.id}/`, form)).data
        : (await api.post<Announcement>('/announcements/', form)).data
    },
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ANNOUNCEMENTS_KEY })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      toast.success(t(announcement ? 'announcements.saved' : 'announcements.posted'))
      onClose()
      if (!announcement) navigate(`/announcements/${saved.id}`)
    },
    onError: (e) => {
      const err = apiError(e)
      setErrors(err.fields)
      toast.error(Object.values(err.fields)[0] ?? err.message)
    },
  })

  /** Wrap the selection (or insert a sample) with formatting markers, keeping the caret sensible. */
  const format = (kind: 'bold' | 'ul' | 'ol' | 'link') => {
    const el = text.current
    if (!el) return
    const start = el.selectionStart
    const end = el.selectionEnd
    const selected = body.slice(start, end)
    let insert: string
    let caret: [number, number]
    if (kind === 'bold') {
      const inner = selected || t('announcements.fmt.boldSample')
      insert = `**${inner}**`
      caret = [start + 2, start + 2 + inner.length]
    } else if (kind === 'link') {
      const label = selected || t('announcements.fmt.linkSample')
      insert = `[${label}](https://)`
      caret = [start + label.length + 3, start + label.length + 11]
    } else {
      const lines = (selected || t('announcements.fmt.itemSample')).split('\n')
      insert = lines.map((l, i) => `${kind === 'ul' ? '-' : `${i + 1}.`} ${l.replace(/^\s*(?:[-*]|\d+[.)])\s+/, '')}`).join('\n')
      // Lists start on their own line.
      if (start > 0 && body[start - 1] !== '\n') insert = `\n${insert}`
      caret = [start + insert.length, start + insert.length]
    }
    const next = body.slice(0, start) + insert + body.slice(end)
    setBody(next)
    setPreview(false)
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(caret[0], caret[1])
    })
  }

  const tools = [
    { kind: 'bold' as const, icon: Bold, label: t('announcements.fmt.bold') },
    { kind: 'ul' as const, icon: List, label: t('announcements.fmt.bullets') },
    { kind: 'ol' as const, icon: ListOrdered, label: t('announcements.fmt.numbers') },
    { kind: 'link' as const, icon: Link2, label: t('announcements.fmt.link') },
  ]
  const myDepartment = departments?.find((d) => d.id === me.department)?.name ?? me.department_name

  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={announcement ? t('announcements.edit') : t('announcements.new')}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !title.trim() || !body.trim()}>
            {announcement ? t('common.save') : t('announcements.post')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <FormField id="ann-title" label={t('announcements.titleLabel')} error={errors.title}>
          <Input id="ann-title" value={title} dir="auto" maxLength={200} onChange={(e) => setTitle(e.target.value)} aria-invalid={!!errors.title} />
        </FormField>

        <FormField id="ann-body" label={t('announcements.body')} error={errors.body} hint={t('announcements.fmt.hint')}>
          <div className="rounded-md border focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50">
            <div className="flex items-center gap-0.5 border-b px-1 py-1" role="toolbar" aria-label={t('announcements.fmt.toolbar')}>
              {tools.map((tool) => (
                <Button key={tool.kind} type="button" variant="ghost" size="icon-sm" onClick={() => format(tool.kind)} aria-label={tool.label} title={tool.label} disabled={preview}>
                  <tool.icon className="size-4" />
                </Button>
              ))}
              <span className="flex-1" />
              <Button type="button" variant="ghost" size="sm" onClick={() => setPreview((p) => !p)} aria-pressed={preview}>
                {preview ? <Pencil className="size-4" /> : <Eye className="size-4" />}
                {preview ? t('announcements.write') : t('announcements.preview')}
              </Button>
            </div>
            {preview ? (
              <div className="min-h-40 p-3">
                {body.trim() ? <AnnouncementBody body={body} /> : <p className="text-sm text-muted-foreground">{t('announcements.previewEmpty')}</p>}
              </div>
            ) : (
              <Textarea
                id="ann-body"
                ref={text}
                value={body}
                dir={textDir(body)}
                maxLength={10000}
                onChange={(e) => setBody(e.target.value)}
                aria-invalid={!!errors.body}
                className="min-h-40 rounded-none border-0 shadow-none focus-visible:ring-0"
              />
            )}
          </div>
        </FormField>

        {isAdmin ? (
          <FormField id="ann-audience" label={t('announcements.audience')} error={errors.audience ?? errors.departments}>
            <SimpleSelect
              id="ann-audience"
              value={audience}
              onChange={(v) => setAudience(v as AnnouncementAudience)}
              options={[
                { value: 'everyone', label: t('announcements.audiences.everyone') },
                { value: 'departments', label: t('announcements.audiences.departments') },
              ]}
            />
            {audience === 'departments' && (
              <div className="mt-1 grid gap-2 rounded-md border p-2.5 sm:grid-cols-2">
                {(departments ?? []).map((d) => (
                  <label key={d.id} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={chosen.includes(d.id)}
                      onCheckedChange={(on) => setChosen((c) => (on ? [...c, d.id] : c.filter((x) => x !== d.id)))}
                    />
                    <bdi>{d.name}</bdi>
                  </label>
                ))}
              </div>
            )}
          </FormField>
        ) : (
          <div className="grid gap-1.5">
            <span className="text-sm font-medium">{t('announcements.audience')}</span>
            <p className="rounded-md bg-muted/60 px-3 py-2 text-sm">{t('announcements.forDepartment', { name: myDepartment ?? '' })}</p>
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
            <span className="grid">
              <span className="text-sm font-medium">{t('announcements.pinned')}</span>
              <span className="text-xs text-muted-foreground">{t('announcements.pinnedHint')}</span>
            </span>
            <Switch checked={pinned} onCheckedChange={setPinned} />
          </label>
          <FormField id="ann-expires" label={t('announcements.expiresOn')} error={errors.expires_on} hint={t('announcements.expiresHint')}>
            <Input id="ann-expires" type="date" value={expires} min={localToday()} onChange={(e) => setExpires(e.target.value)} className="font-latin" />
          </FormField>
        </div>

        <div className="grid gap-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium">{t('announcements.files')}</span>
            <Button type="button" variant="outline" size="sm" onClick={() => picker.current?.click()} disabled={kept.length + files.length >= MAX_FILES}>
              <Paperclip className="size-4" />
              {t('announcements.addFiles')}
            </Button>
            <input
              ref={picker}
              type="file"
              multiple
              hidden
              onChange={(e) => {
                const picked = Array.from(e.target.files ?? [])
                setFiles((f) => [...f, ...picked].slice(0, MAX_FILES - kept.length))
                e.target.value = ''
              }}
            />
          </div>
          {errors.files && <p className="text-xs text-destructive">{errors.files}</p>}
          {kept.length + files.length > 0 ? (
            <ul className="grid gap-1.5">
              {kept.map((a) => (
                <FileRow key={`a${a.id}`} name={a.original_name} onRemove={() => setRemoved((r) => [...r, a.id])} />
              ))}
              {files.map((f, i) => (
                <FileRow key={`f${i}`} name={f.name} isNew onRemove={() => setFiles((list) => list.filter((_, j) => j !== i))} />
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">{t('announcements.filesHint')}</p>
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
      <Button type="button" variant="ghost" size="icon-xs" onClick={onRemove} aria-label={t('announcements.removeFile', { name })}>
        <X className="size-3.5" />
      </Button>
    </li>
  )
}
