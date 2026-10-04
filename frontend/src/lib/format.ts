import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import type { OrgSettings } from './types'

export const ORG_SETTINGS_KEY = ['org-settings'] as const

const DEFAULT_SETTINGS: OrgSettings = {
  org_name: 'Office CRM',
  currency: 'PKR',
  date_format: 'DD/MM/YYYY',
  timezone: 'Asia/Karachi',
  week_start: 1,
  default_language: 'en',
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

export function buildFormatter(settings: OrgSettings, language: string) {
  const locale = LOCALES[language] ?? 'en-PK'
  const timeZone = settings.timezone

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

  const time = (value: DateInput) => {
    const d = toDate(value)
    return d ? new Intl.DateTimeFormat(locale, { timeZone, hour: 'numeric', minute: '2-digit' }).format(d) : '—'
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

  return { date, time, dateTime, relative, currency, number, currentHour, settings }
}

/** Formats dates and money using the organization's settings and the current UI language. */
export function useFormat() {
  const { data } = useOrgSettings()
  const { i18n } = useTranslation()
  const settings = data ?? DEFAULT_SETTINGS
  return useMemo(() => buildFormatter(settings, i18n.language), [settings, i18n.language])
}
