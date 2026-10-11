import { Repeat } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { SimpleSelect } from '@/components/common'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { useFormat } from '@/lib/format'
import { defaultRule, describeRule, weekdayName, type Frequency, type RecurrenceInput } from '@/lib/tasks'
import { cn } from '@/lib/utils'

const LOCALES: Record<string, string> = { en: 'en-PK', ur: 'ur-PK' }
type Ends = 'never' | 'date' | 'count'

/** "Repeat" section of the task form. The due date is the first occurrence. */
export function RepeatEditor({
  value,
  onChange,
  dueDate,
  idPrefix = 'repeat',
  error,
}: {
  value: RecurrenceInput | null
  onChange: (rule: RecurrenceInput | null) => void
  dueDate: string
  idPrefix?: string
  error?: string
}) {
  const { t, i18n } = useTranslation()
  const fmt = useFormat()
  const locale = LOCALES[i18n.language] ?? 'en-PK'
  const id = (name: string) => `${idPrefix}-${name}`
  const set = (patch: Partial<RecurrenceInput>) => value && onChange({ ...value, ...patch })
  // Weekday buttons follow the organization's week start (0 = Sunday, 1 = Monday, 6 = Saturday).
  const firstDay = (fmt.settings.week_start + 6) % 7
  const order = Array.from({ length: 7 }, (_, i) => (firstDay + i) % 7)
  const ends: Ends = value?.end_date ? 'date' : value?.count ? 'count' : 'never'

  return (
    <div className="grid gap-3 rounded-lg border p-3">
      <div className="flex items-center gap-2">
        <Repeat className="size-4 text-muted-foreground" />
        <Label htmlFor={id('on')} className="flex-1">
          {t('tasks.repeat.label')}
        </Label>
        <Switch id={id('on')} checked={!!value} disabled={!dueDate && !value} onCheckedChange={(on) => onChange(on ? defaultRule(dueDate || null) : null)} />
      </div>
      {!dueDate && !value && <p className="text-xs text-muted-foreground">{t('tasks.repeat.needsDueDate')}</p>}

      {value && (
        <>
          <div className="grid grid-cols-[auto_5rem_minmax(0,1fr)] items-center gap-2">
            <Label htmlFor={id('interval')} className="text-sm font-normal text-muted-foreground">
              {t('tasks.repeat.every')}
            </Label>
            <Input
              id={id('interval')}
              type="number"
              min={1}
              max={99}
              value={value.interval}
              onChange={(e) => set({ interval: Math.max(1, Math.min(99, Number(e.target.value) || 1)) })}
              className="font-latin"
            />
            <SimpleSelect
              id={id('frequency')}
              value={value.frequency}
              onChange={(v) => set({ frequency: v as Frequency })}
              options={(['daily', 'weekly', 'monthly'] as const).map((f) => ({ value: f, label: t(`tasks.repeat.units.${f}`, { count: value.interval }) }))}
            />
          </div>

          {value.frequency === 'weekly' && (
            <div role="group" aria-label={t('tasks.repeat.onDays')} className="flex flex-wrap gap-1.5">
              {order.map((d) => {
                const on = value.weekdays.includes(d)
                return (
                  <button
                    key={d}
                    type="button"
                    aria-pressed={on}
                    title={weekdayName(d, locale)}
                    onClick={() => set({ weekdays: on ? value.weekdays.filter((x) => x !== d) : [...value.weekdays, d].sort() })}
                    className={cn(
                      'h-8 min-w-11 rounded-full border px-2 text-sm transition-colors',
                      on ? 'border-primary bg-primary text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted hover:text-foreground',
                    )}
                  >
                    {weekdayName(d, locale, 'short')}
                  </button>
                )
              })}
            </div>
          )}

          {value.frequency === 'monthly' && (
            <fieldset className="grid gap-2">
              <legend className="sr-only">{t('tasks.repeat.monthlyOn')}</legend>
              <label className="flex items-center gap-2 text-sm">
                <input type="radio" name={id('monthly')} checked={value.monthly_mode === 'day'} onChange={() => set({ monthly_mode: 'day' })} className="size-4 accent-primary" />
                {t('tasks.repeat.onDay')}
                <Input
                  type="number"
                  min={1}
                  max={31}
                  aria-label={t('tasks.repeat.dayOfMonth')}
                  value={value.month_day ?? 1}
                  disabled={value.monthly_mode !== 'day'}
                  onChange={(e) => set({ month_day: Math.max(1, Math.min(31, Number(e.target.value) || 1)) })}
                  className="h-8 w-20 font-latin"
                />
              </label>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <label className="flex items-center gap-2">
                  <input type="radio" name={id('monthly')} checked={value.monthly_mode === 'weekday'} onChange={() => set({ monthly_mode: 'weekday' })} className="size-4 accent-primary" />
                  {t('tasks.repeat.onThe')}
                </label>
                <SimpleSelect
                  className="w-auto min-w-28"
                  disabled={value.monthly_mode !== 'weekday'}
                  value={String(value.month_week ?? 1)}
                  onChange={(v) => set({ month_week: Number(v) })}
                  options={['1', '2', '3', '4', '-1'].map((w) => ({ value: w, label: t(`tasks.repeat.ordinals.${w === '-1' ? 'last' : w}`) }))}
                />
                <SimpleSelect
                  className="w-auto min-w-32"
                  disabled={value.monthly_mode !== 'weekday'}
                  value={String(value.month_weekday ?? 0)}
                  onChange={(v) => set({ month_weekday: Number(v) })}
                  options={order.map((d) => ({ value: String(d), label: weekdayName(d, locale) }))}
                />
              </div>
              <p className="text-xs text-muted-foreground">{t('tasks.repeat.monthEndHint')}</p>
            </fieldset>
          )}

          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Label htmlFor={id('ends')} className="font-normal text-muted-foreground">
              {t('tasks.repeat.ends')}
            </Label>
            <SimpleSelect
              id={id('ends')}
              className="w-auto min-w-36"
              value={ends}
              onChange={(v) =>
                set(v === 'never' ? { end_date: null, count: null } : v === 'date' ? { end_date: dueDate, count: null } : { end_date: null, count: 10 })
              }
              options={(['never', 'date', 'count'] as const).map((e) => ({ value: e, label: t(`tasks.repeat.endOptions.${e}`) }))}
            />
            {ends === 'date' && (
              <Input
                type="date"
                aria-label={t('tasks.repeat.endDate')}
                value={value.end_date ?? ''}
                min={dueDate}
                onChange={(e) => set({ end_date: e.target.value || null })}
                className="h-8 w-auto font-latin"
              />
            )}
            {ends === 'count' && (
              <>
                <Input
                  type="number"
                  min={1}
                  max={500}
                  aria-label={t('tasks.repeat.occurrences')}
                  value={value.count ?? 1}
                  onChange={(e) => set({ count: Math.max(1, Math.min(500, Number(e.target.value) || 1)) })}
                  className="h-8 w-20 font-latin"
                />
                <span className="text-muted-foreground">{t('tasks.repeat.timesLabel')}</span>
              </>
            )}
          </div>

          <p className="flex items-center gap-1.5 rounded-md bg-muted/50 px-2.5 py-1.5 text-sm" aria-live="polite">
            <Repeat className="size-3.5 shrink-0 text-primary" />
            {value.frequency === 'weekly' && value.weekdays.length === 0
              ? t('tasks.repeat.pickDays')
              : describeRule(value, t, locale, fmt.date)}
          </p>
        </>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}
