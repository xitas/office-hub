import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { FormField, SimpleSelect } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { TemplatePicker } from '@/features/templates/TemplatePicker'
import { fillTemplate, recordTemplateUse, type MessageTemplate } from '@/lib/templates'
import { toast } from 'sonner'
import { usePermission } from '@/lib/permissions'
import { useTaskAssignees } from '@/lib/tasks'
import {
  CALL_DIRECTIONS,
  CALL_OUTCOMES,
  ENTRY_KINDS,
  KIND_ICONS,
  toLocalInput,
  type CallDetails,
  type EmailDetails,
  type EntryInput,
  type EntryKind,
  type MeetingDetails,
  type TimelineItem,
} from '@/lib/timeline'
import { cn } from '@/lib/utils'

interface Props {
  /** Entry being edited (its type can't change). */
  entry?: TimelineItem
  kinds?: readonly EntryKind[]
  /** New entry: start on this type (e.g. "call" after tapping Call), going this way. */
  initialKind?: EntryKind
  initialDirection?: 'in' | 'out'
  initialSummary?: string
  initialSubject?: string
  /** The contact being logged on: "From template" fills in their details. */
  contactId?: number
  /** Or the vendor: its contact person and details fill the template. */
  vendorId?: number
  onSubmit: (input: Partial<EntryInput>) => Promise<unknown>
  onCancel?: () => void
  /** Prefix for element ids, so two forms can sit on one page. */
  idPrefix?: string
  autoFocus?: boolean
}

/** Add/edit form for a note, call, meeting, email or WhatsApp message. Shows the extra fields of the
 *  chosen type, and with a follow-up date who the follow-up task goes to (or no task). */
export function EntryForm({
  entry,
  kinds = ENTRY_KINDS,
  initialKind,
  initialDirection,
  initialSummary,
  initialSubject,
  contactId,
  vendorId,
  onSubmit,
  onCancel,
  idPrefix = 'entry',
  autoFocus,
}: Props) {
  const { t } = useTranslation()
  const me = useMe()
  const canCreateTasks = usePermission('tasks.create')
  const assignees = useTaskAssignees()
  const call = (entry?.details ?? {}) as CallDetails
  const meeting = (entry?.details ?? {}) as MeetingDetails
  const email = (entry?.details ?? {}) as EmailDetails
  const [kind, setKind] = useState<EntryKind>((entry?.kind as EntryKind) ?? initialKind ?? kinds[0])
  const [summary, setSummary] = useState(entry?.summary ?? initialSummary ?? '')
  const [direction, setDirection] = useState<string>(call.direction ?? initialDirection ?? 'out')
  const [outcome, setOutcome] = useState<string>(call.outcome ?? 'connected')
  const [duration, setDuration] = useState(call.duration_minutes != null ? String(call.duration_minutes) : '')
  const [location, setLocation] = useState(meeting.location ?? '')
  const [attendees, setAttendees] = useState(meeting.attendees ?? '')
  const [subject, setSubject] = useState(email.subject ?? initialSubject ?? '')
  // Blank "when" means "now" (filled in by the server when saving).
  const [when, setWhen] = useState(entry ? toLocalInput(entry.occurred_at) : '')
  const [followUp, setFollowUp] = useState(entry?.follow_up_on ?? '')
  const [assignee, setAssignee] = useState(String(me.id))
  const [skipTask, setSkipTask] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)
  const [now] = useState(() => toLocalInput(new Date()))
  const id = (name: string) => `${idPrefix}-${name}`

  // A task is made when a follow-up date is set (new entry) or changed on an entry that has no task yet.
  const makesTask =
    canCreateTasks && !!followUp && (!entry || (!entry.follow_up_task && followUp !== (entry.follow_up_on ?? '')))

  const reset = () => {
    setSummary('')
    setDuration('')
    setLocation('')
    setAttendees('')
    setSubject('')
    setWhen('')
    setFollowUp('')
    setAssignee(String(me.id))
    setSkipTask(false)
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const details =
      kind === 'call'
        ? { direction, outcome, duration_minutes: duration === '' ? null : Number(duration) }
        : kind === 'meeting'
          ? { location: location.trim(), attendees: attendees.trim() }
          : kind === 'email'
            ? { direction, subject: subject.trim() }
            : kind === 'whatsapp'
              ? { direction }
              : {}
    const input: Partial<EntryInput> = {
      summary: summary.trim(),
      details: details as EntryInput['details'],
      follow_up_on: followUp || null,
    }
    if (!entry) input.kind = kind
    if (when) input.occurred_at = new Date(when).toISOString()
    if (makesTask) {
      input.follow_up_skip = skipTask
      if (!skipTask && assignee !== String(me.id)) input.follow_up_assignee = Number(assignee)
    }
    setSaving(true)
    setErrors({})
    setMessage('')
    try {
      await onSubmit(input)
      if (!entry) reset()
    } catch (err) {
      const info = apiError(err)
      setErrors(info.fields)
      setMessage(Object.keys(info.fields).length ? '' : info.message)
    } finally {
      setSaving(false)
    }
  }

  // "From template": the summary (and an email's subject) start from a template filled for this contact.
  const fromTemplate = async (template: MessageTemplate) => {
    try {
      const filled = await fillTemplate(template.id, contactId, vendorId)
      setSummary(filled.body)
      if (kind === 'email' && filled.subject) setSubject(filled.subject)
      recordTemplateUse(template.id)
      if (filled.unknown.length || filled.empty.length) toast.warning(t('templates.checkText'))
    } catch {
      toast.error(t('templates.fillFailed'))
    }
  }

  const placeholder = t(`timeline.placeholders.${kind}`)
  const showKinds = !entry && kinds.length > 1
  const directionField = (
    <FormField id={id('direction')} label={t('timeline.direction')}>
      <SimpleSelect
        id={id('direction')}
        value={direction}
        onChange={setDirection}
        options={CALL_DIRECTIONS.map((d) => ({ value: d, label: t(`timeline.directionsFor.${kind}.${d}`) }))}
      />
    </FormField>
  )

  return (
    <form onSubmit={(e) => void submit(e)} className="grid gap-3">
      {showKinds && (
        <div role="radiogroup" aria-label={t('timeline.type')} className="flex flex-wrap gap-1.5">
          {kinds.map((k) => {
            const Icon = KIND_ICONS[k]
            const active = k === kind
            return (
              <button
                key={k}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => setKind(k)}
                className={cn(
                  'inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-sm transition-colors',
                  active
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground',
                )}
              >
                <Icon className="size-3.5" />
                {t(`timeline.kinds.${k}`)}
              </button>
            )
          })}
        </div>
      )}

      {kind === 'call' && (
        <div className="grid gap-3 sm:grid-cols-3">
          {directionField}
          <FormField id={id('outcome')} label={t('timeline.outcome')}>
            <SimpleSelect
              id={id('outcome')}
              value={outcome}
              onChange={setOutcome}
              options={CALL_OUTCOMES.map((o) => ({ value: o, label: t(`timeline.outcomes.${o}`) }))}
            />
          </FormField>
          <FormField id={id('duration')} label={t('timeline.durationMinutes')} error={errors.details}>
            <Input
              id={id('duration')}
              type="number"
              inputMode="numeric"
              min={0}
              max={600}
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
              className="font-latin"
            />
          </FormField>
        </div>
      )}

      {kind === 'email' && (
        <div className="grid gap-3 sm:grid-cols-[12rem_1fr]">
          {directionField}
          <FormField id={id('subject')} label={t('timeline.subject')} error={errors.details}>
            <Input id={id('subject')} value={subject} maxLength={200} dir="auto" onChange={(e) => setSubject(e.target.value)} />
          </FormField>
        </div>
      )}

      {kind === 'whatsapp' && <div className="grid gap-3 sm:grid-cols-[12rem_1fr]">{directionField}</div>}

      {kind === 'meeting' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField id={id('location')} label={t('timeline.location')}>
            <Input id={id('location')} value={location} maxLength={200} onChange={(e) => setLocation(e.target.value)} />
          </FormField>
          <FormField id={id('attendees')} label={t('timeline.attendees')} error={errors.details}>
            <Input
              id={id('attendees')}
              value={attendees}
              maxLength={500}
              placeholder={t('timeline.attendeesHint')}
              onChange={(e) => setAttendees(e.target.value)}
            />
          </FormField>
        </div>
      )}

      {!entry && (
        <div className="-mb-2 flex justify-end">
          <TemplatePicker
            channel={kind === 'email' || kind === 'whatsapp' ? kind : 'any'}
            label={t('templates.fromTemplate')}
            align="end"
            onPick={(tpl) => void fromTemplate(tpl)}
          />
        </div>
      )}
      <FormField id={id('summary')} label={t(kind === 'note' ? 'timeline.note' : 'timeline.summary')} error={errors.summary}>
        <Textarea
          id={id('summary')}
          value={summary}
          maxLength={5000}
          rows={3}
          dir="auto"
          placeholder={placeholder}
          autoFocus={autoFocus}
          aria-invalid={!!errors.summary}
          onChange={(e) => setSummary(e.target.value)}
          className="min-h-20"
        />
      </FormField>

      <div className="grid gap-3 sm:grid-cols-2">
        <FormField id={id('when')} label={t('timeline.when')} error={errors.occurred_at} hint={entry ? undefined : t('timeline.whenHint')}>
          <Input
            id={id('when')}
            type="datetime-local"
            value={when}
            max={now}
            onChange={(e) => setWhen(e.target.value)}
            className="font-latin"
          />
        </FormField>
        <FormField id={id('follow-up')} label={t('timeline.followUp')} error={errors.follow_up_on} hint={t('timeline.followUpTaskHint')}>
          <Input
            id={id('follow-up')}
            type="date"
            value={followUp}
            onChange={(e) => setFollowUp(e.target.value)}
            className="font-latin"
          />
        </FormField>
      </div>

      {makesTask && (
        <fieldset className="grid gap-3 rounded-lg border bg-muted/30 p-3 sm:grid-cols-2 sm:items-end">
          <legend className="px-1 text-xs font-medium text-muted-foreground">{t('timeline.followUpTask')}</legend>
          <FormField id={id('assignee')} label={t('timeline.followUpAssignee')} error={errors.follow_up_assignee}>
            <SimpleSelect
              id={id('assignee')}
              value={assignee}
              disabled={skipTask}
              onChange={setAssignee}
              options={(assignees.length ? assignees : [{ id: me.id, full_name: me.full_name }]).map((u) => ({
                value: String(u.id),
                label: u.id === me.id ? t('timeline.me', { name: u.full_name }) : u.full_name,
              }))}
            />
          </FormField>
          <div className="flex items-center gap-2 sm:mb-2">
            <Checkbox id={id('skip')} checked={skipTask} onCheckedChange={(v) => setSkipTask(v === true)} />
            <Label htmlFor={id('skip')} className="font-normal">
              {t('timeline.followUpSkip')}
            </Label>
          </div>
        </fieldset>
      )}

      <div className="flex justify-end gap-2">
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
        )}
        <Button type="submit" disabled={saving}>
          {saving ? t('common.saving') : entry ? t('common.save') : t('timeline.add')}
        </Button>
      </div>
      {message && <p className="text-sm text-destructive">{message}</p>}
    </form>
  )
}
