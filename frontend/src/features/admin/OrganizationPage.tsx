import { useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { ErrorState, FormField, PageHeader, SimpleSelect, TextField } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { api, apiError } from '@/lib/api'
import { buildFormatter, ORG_SETTINGS_KEY, useOrgSettings } from '@/lib/format'
import { weekdayName } from '@/lib/tasks'
import type { OrgSettings } from '@/lib/types'

const DATE_FORMATS: OrgSettings['date_format'][] = ['DD/MM/YYYY', 'MM/DD/YYYY', 'YYYY-MM-DD', 'DD MMM YYYY']
const COMMON_TIMEZONES = ['Asia/Karachi', 'Asia/Dubai', 'Asia/Riyadh', 'Asia/Kolkata', 'Europe/London', 'America/New_York', 'UTC']

export function OrganizationPage() {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useOrgSettings()

  return (
    <>
      <PageHeader title={t('admin.org.title')} subtitle={t('admin.org.subtitle')} />
      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading || !data ? (
        <Skeleton className="h-96 max-w-2xl rounded-xl" />
      ) : (
        <OrgForm initial={data} />
      )}
    </>
  )
}

function OrgForm({ initial }: { initial: OrgSettings }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [form, setForm] = useState(initial)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [now] = useState(() => new Date())

  const set = <K extends keyof OrgSettings>(key: K, value: OrgSettings[K]) => setForm((f) => ({ ...f, [key]: value }))
  const preview = useMemo(() => {
    const valid = /^[A-Za-z]{3}$/.test(form.currency)
    const fmt = buildFormatter({ ...form, currency: valid ? form.currency.toUpperCase() : 'PKR' }, i18n.language)
    try {
      return `${fmt.dateTime(now)} · ${fmt.currency(125000)}`
    } catch {
      return '—'
    }
  }, [form, i18n.language, now])

  const timezones = COMMON_TIMEZONES.includes(form.timezone) ? COMMON_TIMEZONES : [form.timezone, ...COMMON_TIMEZONES]

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErrors({})
    try {
      const { data } = await api.patch<OrgSettings>('/settings/organization/', form)
      queryClient.setQueryData(ORG_SETTINGS_KEY, data)
      toast.success(t('common.saved'))
    } catch (err) {
      const info = apiError(err)
      setErrors(info.fields)
      toast.error(info.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="max-w-2xl">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <CardHeader>
          <CardTitle>{t('admin.org.title')}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <TextField
            id="org-name"
            className="sm:col-span-2"
            label={t('admin.org.orgName')}
            value={form.org_name}
            onChange={(e) => set('org_name', e.target.value)}
            error={errors.org_name}
            required
          />
          <TextField
            id="org-currency"
            label={t('admin.org.currency')}
            hint={t('admin.org.currencyHint')}
            value={form.currency}
            onChange={(e) => set('currency', e.target.value.toUpperCase().slice(0, 3))}
            error={errors.currency}
            dir="ltr"
            className="font-latin"
            required
          />
          <FormField id="org-date" label={t('admin.org.dateFormat')} error={errors.date_format}>
            <SimpleSelect
              id="org-date"
              value={form.date_format}
              onChange={(v) => set('date_format', v as OrgSettings['date_format'])}
              options={DATE_FORMATS.map((f) => ({ value: f, label: f }))}
            />
          </FormField>
          <FormField id="org-tz" label={t('admin.org.timezone')} error={errors.timezone}>
            <SimpleSelect id="org-tz" value={form.timezone} onChange={(v) => set('timezone', v)} options={timezones.map((z) => ({ value: z, label: z }))} />
          </FormField>
          <FormField id="org-week" label={t('admin.org.weekStart')} error={errors.week_start}>
            <SimpleSelect
              id="org-week"
              value={String(form.week_start)}
              onChange={(v) => set('week_start', Number(v))}
              options={['1', '0', '6'].map((d) => ({ value: d, label: t(`admin.org.days.${d}`) }))}
            />
          </FormField>
          <FormField id="org-clock" label={t('admin.org.timeFormat')} hint={t('admin.org.timeFormatHint')} error={errors.time_format}>
            <SimpleSelect
              id="org-clock"
              value={form.time_format}
              onChange={(v) => set('time_format', v as OrgSettings['time_format'])}
              options={[
                { value: '12h', label: t('settings.clock12') },
                { value: '24h', label: t('settings.clock24') },
              ]}
            />
          </FormField>
          <FormField id="org-lang" label={t('admin.org.defaultLanguage')} error={errors.default_language}>
            <SimpleSelect
              id="org-lang"
              value={form.default_language}
              onChange={(v) => set('default_language', v as OrgSettings['default_language'])}
              options={['en', 'ur'].map((l) => ({ value: l, label: t(`languages.${l}`) }))}
            />
          </FormField>
          <fieldset className="grid gap-4 border-t pt-4 sm:col-span-2 sm:grid-cols-2">
            <legend className="sr-only">{t('admin.org.bookings')}</legend>
            <div className="grid gap-0.5 sm:col-span-2">
              <p className="text-sm font-medium">{t('admin.org.bookings')}</p>
              <p className="text-xs text-muted-foreground">{t('admin.org.bookingsHint')}</p>
            </div>
            <TextField
              id="org-opens"
              type="time"
              step={900}
              label={t('admin.org.officeOpens')}
              value={form.office_opens.slice(0, 5)}
              onChange={(e) => set('office_opens', e.target.value)}
              error={errors.office_opens}
              className="font-latin"
              required
            />
            <TextField
              id="org-closes"
              type="time"
              step={900}
              label={t('admin.org.officeCloses')}
              value={form.office_closes.slice(0, 5)}
              onChange={(e) => set('office_closes', e.target.value)}
              error={errors.office_closes}
              className="font-latin"
              required
            />
            <FormField id="org-max" label={t('admin.org.bookingMax')} error={errors.booking_max_minutes}>
              <SimpleSelect
                id="org-max"
                value={String(form.booking_max_minutes)}
                onChange={(v) => set('booking_max_minutes', Number(v))}
                options={[...new Set([30, 60, 90, 120, 180, 240, 360, 480, 600, 720, form.booking_max_minutes])]
                  .sort((a, b) => a - b)
                  .map((m) => ({ value: String(m), label: t('admin.org.duration', { h: Math.floor(m / 60), m: String(m % 60).padStart(2, '0') }) }))}
              />
            </FormField>
            <TextField
              id="org-horizon"
              type="number"
              min={1}
              max={730}
              label={t('admin.org.bookingHorizon')}
              hint={t('admin.org.bookingHorizonHint')}
              value={String(form.booking_horizon_days)}
              onChange={(e) => set('booking_horizon_days', Number(e.target.value))}
              error={errors.booking_horizon_days}
              className="font-latin"
              required
            />
            <div className="grid gap-1.5 sm:col-span-2">
              <span className="text-sm font-medium">{t('admin.org.workingDays')}</span>
              <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('admin.org.workingDays')}>
                {[0, 1, 2, 3, 4, 5, 6].map((d) => {
                  const on = form.working_days.includes(d)
                  return (
                    <button
                      key={d}
                      type="button"
                      aria-pressed={on}
                      onClick={() => set('working_days', on ? form.working_days.filter((x) => x !== d) : [...form.working_days, d].sort())}
                      className={on ? 'rounded-full border border-primary bg-primary px-3 py-1 text-xs text-primary-foreground' : 'rounded-full border px-3 py-1 text-xs hover:bg-muted'}
                    >
                      {weekdayName(d, i18n.language === 'ur' ? 'ur-PK' : 'en-GB', 'short')}
                    </button>
                  )
                })}
              </div>
              <p className="text-xs text-muted-foreground">{errors.working_days ?? t('admin.org.workingDaysHint')}</p>
            </div>
          </fieldset>
          <fieldset className="grid gap-4 border-t pt-4 sm:col-span-2 sm:grid-cols-2">
            <legend className="sr-only">{t('admin.org.attendance')}</legend>
            <p className="text-sm font-medium sm:col-span-2">{t('admin.org.attendance')}</p>
            <TextField
              id="org-late"
              type="number"
              min={0}
              max={240}
              label={t('admin.org.lateAfter')}
              hint={t('admin.org.lateAfterHint')}
              value={String(form.late_after_minutes)}
              onChange={(e) => set('late_after_minutes', Number(e.target.value))}
              error={errors.late_after_minutes}
              className="font-latin"
              required
            />
            <div className="flex items-start justify-between gap-4 sm:col-span-2">
              <div className="grid gap-0.5">
                <label htmlFor="org-att-reminders" className="text-sm">
                  {t('admin.org.attendanceReminders')}
                </label>
                <p className="text-xs text-muted-foreground">{t('admin.org.attendanceRemindersHint')}</p>
              </div>
              <Switch id="org-att-reminders" checked={form.attendance_reminders} onCheckedChange={(v) => set('attendance_reminders', v)} />
            </div>
          </fieldset>
          <fieldset className="grid gap-3 border-t pt-4 sm:col-span-2">
            <legend className="sr-only">{t('admin.org.staffAccess')}</legend>
            <p className="text-sm font-medium">{t('admin.org.staffAccess')}</p>
            {(['staff_can_import_contacts', 'staff_can_export_contacts'] as const).map((key) => (
              <div key={key} className="flex items-start justify-between gap-4">
                <div className="grid gap-0.5">
                  <label htmlFor={`org-${key}`} className="text-sm">
                    {t(`admin.org.${key}`)}
                  </label>
                  <p className="text-xs text-muted-foreground">{t(`admin.org.${key}_hint`)}</p>
                </div>
                <Switch id={`org-${key}`} checked={form[key]} onCheckedChange={(v) => set(key, v)} />
              </div>
            ))}
          </fieldset>
          <div className="rounded-lg bg-muted p-3 text-sm sm:col-span-2">
            <span className="text-muted-foreground">{t('admin.org.preview')}: </span>
            <span className="font-medium">{preview}</span>
          </div>
        </CardContent>
        <CardFooter className="justify-end">
          <Button type="submit" disabled={busy}>
            {busy && <Loader2 className="size-4 animate-spin" />}
            {busy ? t('common.saving') : t('common.save')}
          </Button>
        </CardFooter>
      </form>
    </Card>
  )
}
