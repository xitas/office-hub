import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { useAuth } from './auth'
import type { OrgSettings, TimeFormat } from './types'

export const ORG_SETTINGS_KEY = ['org-settings'] as const

const DEFAULT_SETTINGS: OrgSettings = {
  org_name: 'Office CRM',
  currency: 'PKR',
  date_format: 'DD/MM/YYYY',
  timezone: 'Asia/Karachi',
  week_start: 1,
  time_format: '12h',
  default_language: 'en',
  staff_can_import_contacts: true,
  staff_can_export_contacts: false,
  office_opens: '09:00:00',
  office_closes: '18:00:00',
  booking_max_minutes: 480,
  booking_horizon_days: 60,
  working_days: [0, 1, 2, 3, 4],
  late_after_minutes: 15,
  attendance_reminders: true,
  updated_at: '',
}

export function useOrgSettings() {
  return useQuery({
    queryKey: ORG_SETTINGS_KEY,
    queryFn: async () => (await api.get<OrgSettings>('/settings/organization/')).data,
    staleTime: 5 * 60_000,
  })
}

const LOCALES: Record<string, string> = { en: 'en-PK', ur: 'ur-PK' }

type DateInput = string | number | Date | null | undefined

function toDate(value: DateInput): Date | null {
  if (value === null || value === undefined || value === '') return null
  const d = value instanceof Date ? value : new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

/** Keeps "9:00 AM" in that order inside right-to-left (Urdu) text, wherever it is shown (Unicode isolate). */
const ltr = (text: string) => `\u2066${text}\u2069`

/** Keeps an Urdu time ("صبح 9:00") together as right-to-left text. */
const rtl = (text: string) => `\u2067${text}\u2069`

/** صبح 5–12, دوپہر 12–16, شام 16–20, رات 20–5: the same bands as the server's emails and notifications. */
export function urduDayPeriod(hour: number) {
  if (hour >= 5 && hour < 12) return 'صبح'
  if (hour >= 12 && hour < 16) return 'دوپہر'
  if (hour >= 16 && hour < 20) return 'شام'
  return 'رات'
}

export function buildFormatter(settings: OrgSettings, language: string, timeFormat: TimeFormat = settings.time_format) {
  const locale = LOCALES[language] ?? 'en-PK'
  const timeZone = settings.timezone
  const hourCycle = timeFormat === '24h' ? 'h23' : 'h12'

  const partsOf = (d: Date, month: '2-digit' | 'short') => {
    const parts = new Intl.DateTimeFormat(locale, {
      timeZone,
      day: '2-digit',
      month,
      year: 'numeric',
      numberingSystem: 'latn',
    }).formatToParts(d)
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? ''
    return { day: get('day'), month: get('month'), year: get('year') }
  }

  const date = (value: DateInput) => {
    const d = toDate(value)
    if (!d) return '—'
    switch (settings.date_format) {
      case 'MM/DD/YYYY': {
        const p = partsOf(d, '2-digit')
        return `${p.month}/${p.day}/${p.year}`
      }
      case 'YYYY-MM-DD': {
        const p = partsOf(d, '2-digit')
        return `${p.year}-${p.month}-${p.day}`
      }
      case 'DD MMM YYYY': {
        const p = partsOf(d, 'short')
        return `${p.day} ${p.month} ${p.year}`
      }
      default: {
        const p = partsOf(d, '2-digit')
        return `${p.day}/${p.month}/${p.year}`
      }
    }
  }

  /** "9:00 AM" / "14:00"; in Urdu with the 12-hour clock, the part of the day first: "صبح 9:00". */
  const formatClock = (h: number, m: number) => {
    if (hourCycle === 'h12' && language === 'ur') return rtl(`${urduDayPeriod(h)} ${h % 12 || 12}:${String(m).padStart(2, '0')}`)
    return ltr(new Intl.DateTimeFormat(locale, { timeZone: 'UTC', hour: 'numeric', minute: '2-digit', hourCycle }).format(new Date(Date.UTC(2000, 0, 1, h, m))))
  }

  const time = (value: DateInput) => {
    const d = toDate(value)
    if (!d) return '—'
    const [h, m] = new Intl.DateTimeFormat('en-GB', { timeZone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(d).split(':').map(Number)
    return formatClock(h, m)
  }

  /** A wall-clock time "HH:MM" (office time: timelines, time pickers) in the chosen 12- or 24-hour clock. */
  const clock = (hhmm: string) => {
    const [h, m] = hhmm.split(':').map(Number)
    return formatClock(h, m)
  }

  const dateTime = (value: DateInput) => {
    const d = toDate(value)
    return d ? `${date(d)} ${time(d)}` : '—'
  }

  const relative = (value: DateInput) => {
    const d = toDate(value)
    if (!d) return '—'
    const seconds = Math.round((d.getTime() - Date.now()) / 1000)
    const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
    const abs = Math.abs(seconds)
    if (abs < 60) return rtf.format(seconds, 'second')
    if (abs < 3600) return rtf.format(Math.round(seconds / 60), 'minute')
    if (abs < 86400) return rtf.format(Math.round(seconds / 3600), 'hour')
    if (abs < 86400 * 7) return rtf.format(Math.round(seconds / 86400), 'day')
    return date(d)
  }

  const currency = (amount: number | string | null | undefined, code = settings.currency) => {
    if (amount === null || amount === undefined || amount === '') return '—'
    return new Intl.NumberFormat(locale, { style: 'currency', currency: code, maximumFractionDigits: 2 }).format(
      Number(amount),
    )
  }

  const number = (value: number) => new Intl.NumberFormat(locale).format(value)

  /** Current hour (0-23) in the organization's time zone, not the browser's. */
  const currentHour = () =>
    Number(new Intl.DateTimeFormat('en-US', { timeZone, hour: 'numeric', hourCycle: 'h23' }).format(new Date()))

  return { date, time, clock, dateTime, relative, currency, number, currentHour, settings, timeFormat }
}

/** Formats dates, times and money using the organization's settings, the person's clock choice and the UI language. */
export function useFormat() {
  const { data } = useOrgSettings()
  const { user } = useAuth()
  const { i18n } = useTranslation()
  const settings = data ?? DEFAULT_SETTINGS
  const timeFormat = user?.time_format || settings.time_format
  return useMemo(() => buildFormatter(settings, i18n.language, timeFormat), [settings, i18n.language, timeFormat])
}
