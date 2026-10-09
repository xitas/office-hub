import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { FormField, SimpleSelect } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { apiError } from '@/lib/api'
import {
  CALL_DIRECTIONS,
  CALL_OUTCOMES,
  ENTRY_KINDS,
  KIND_ICONS,
  toLocalInput,
  type CallDetails,
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
  onSubmit: (input: Partial<EntryInput>) => Promise<unknown>
  onCancel?: () => void
  /** Prefix for element ids, so two forms can sit on one page. */
  idPrefix?: string
  autoFocus?: boolean
}

/** Add/edit form for a note, call or meeting. Shows the extra fields of the chosen type. */
export function EntryForm({ entry, kinds = ENTRY_KINDS, onSubmit, onCancel, idPrefix = 'entry', autoFocus }: Props) {
  const { t } = useTranslation()
  const call = (entry?.details ?? {}) as CallDetails
  const meeting = (entry?.details ?? {}) as MeetingDetails
  const [kind, setKind] = useState<EntryKind>((entry?.kind as EntryKind) ?? kinds[0])
  const [summary, setSummary] = useState(entry?.summary ?? '')
  const [direction, setDirection] = useState<string>(call.direction ?? 'out')
  const [outcome, setOutcome] = useState<string>(call.outcome ?? 'connected')
  const [duration, setDuration] = useState(call.duration_minutes != null ? String(call.duration_minutes) : '')
  const [location, setLocation] = useState(meeting.location ?? '')
  const [attendees, setAttendees] = useState(meeting.attendees ?? '')
  // Blank "when" means "now" (filled in by the server when saving).
  const [when, setWhen] = useState(entry ? toLocalInput(entry.occurred_at) : '')
  const [followUp, setFollowUp] = useState(entry?.follow_up_on ?? '')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)
  const [now] = useState(() => toLocalInput(new Date()))
  const id = (name: string) => `${idPrefix}-${name}`

  const reset = () => {
    setSummary('')
    setDuration('')
    setLocation('')
    setAttendees('')
    setWhen('')
    setFollowUp('')
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const details =
      kind === 'call'
        ? { direction, outcome, duration_minutes: duration === '' ? null : Number(duration) }
        : kind === 'meeting'
          ? { location: location.trim(), attendees: attendees.trim() }
          : {}
    const input: Partial<EntryInput> = {
      summary: summary.trim(),
      details: details as EntryInput['details'],
      follow_up_on: followUp || null,
    }
    if (!entry) input.kind = kind
    if (when) input.occurred_at = new Date(when).toISOString()
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

  const placeholder = t(`timeline.placeholders.${kind}`)
  const showKinds = !entry && kinds.length > 1

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
          <FormField id={id('direction')} label={t('timeline.direction')}>
            <SimpleSelect
              id={id('direction')}
              value={direction}
              onChange={setDirection}
              options={CALL_DIRECTIONS.map((d) => ({ value: d, label: t(`timeline.directions.${d}`) }))}
            />
          </FormField>
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

      <FormField id={id('summary')} label={t(kind === 'note' ? 'timeline.note' : 'timeline.summary')} error={errors.summary}>
        <Textarea
          id={id('summary')}
          value={summary}
          maxLength={5000}
          rows={3}
          placeholder={placeholder}
          autoFocus={autoFocus}
          aria-invalid={!!errors.summary}
          onChange={(e) => setSummary(e.target.value)}
          className="min-h-20"
        />
      </FormField>

      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
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
        <FormField id={id('follow-up')} label={t('timeline.followUp')} error={errors.follow_up_on} hint={t('timeline.followUpHint')}>
          <Input
            id={id('follow-up')}
            type="date"
            value={followUp}
            onChange={(e) => setFollowUp(e.target.value)}
            className="font-latin"
          />
        </FormField>
        <div className="flex gap-2 sm:mb-5 sm:justify-end">
          {onCancel && (
            <Button type="button" variant="ghost" onClick={onCancel}>
              {t('common.cancel')}
            </Button>
          )}
          <Button type="submit" disabled={saving}>
            {saving ? t('common.saving') : entry ? t('common.save') : t('timeline.add')}
          </Button>
        </div>
      </div>
      {message && <p className="text-sm text-destructive">{message}</p>}
    </form>
  )
}
