import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { whatsappNumber } from './queries'

export const TEMPLATE_CATEGORIES = ['quotation', 'reminder', 'thank_you', 'follow_up', 'general'] as const
export const TEMPLATE_CHANNELS = ['email', 'whatsapp', 'chat', 'any'] as const
export const TEMPLATE_LANGUAGES = ['en', 'ur'] as const
export const TEMPLATE_SHARING = ['personal', 'department', 'everyone'] as const

export type TemplateChannel = (typeof TEMPLATE_CHANNELS)[number]

export interface MessageTemplate {
  id: number
  name: string
  category: (typeof TEMPLATE_CATEGORIES)[number]
  channel: TemplateChannel
  language: (typeof TEMPLATE_LANGUAGES)[number]
  subject: string
  body: string
  sharing: (typeof TEMPLATE_SHARING)[number]
  department: number | null
  department_name: string | null
  created_by: number | null
  created_by_name: string | null
  archived: boolean
  usage_count: number
  last_used_at: string | null
  can_edit: boolean
  unknown_placeholders: string[]
  created_at: string
  updated_at: string
}

export interface TemplateInput {
  name: string
  category: string
  channel: string
  language: string
  subject: string
  body: string
  sharing: string
}

export interface PlaceholderInfo {
  key: string
  label: string
  example: string
}

/** A template (or editor text) filled for a contact and me. */
export interface FilledTemplate {
  subject: string
  body: string
  /** Written like a placeholder but not one (kept as written). */
  unknown: string[]
  /** Known but empty for this contact (left blank). */
  empty: string[]
  whatsapp_url: string | null
  mailto_url: string | null
}

export const TEMPLATES_KEY = ['templates'] as const

export function useTemplates(filters: Record<string, string | undefined> = {}, enabled = true) {
  return useQuery({
    queryKey: [...TEMPLATES_KEY, 'list', filters],
    queryFn: async () => (await api.get<MessageTemplate[]>('/templates/', { params: filters })).data,
    enabled,
    staleTime: 30_000,
  })
}

export function usePlaceholders() {
  return useQuery({
    queryKey: [...TEMPLATES_KEY, 'placeholders'],
    queryFn: async () => (await api.get<PlaceholderInfo[]>('/templates/placeholders/')).data,
    staleTime: Infinity,
  })
}

export async function fillTemplate(id: number, contact?: number | null) {
  return (await api.post<FilledTemplate>(`/templates/${id}/fill/`, { contact: contact ?? null })).data
}

/** Count one use (sent, inserted or copied); errors are ignored, it's only for sorting. */
export function recordTemplateUse(id: number) {
  void api.post(`/templates/${id}/use/`).catch(() => {})
}

/** Text direction for a template's language (Urdu right to left). */
export const templateDir = (language: string) => (language === 'ur' ? 'rtl' : 'ltr')

/** Copy text to the clipboard; false if the browser refused (e.g. not https). */
export async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

/** WhatsApp link with the message typed in (UTF-8, line breaks kept). */
export function whatsappUrl(phone: string, text: string) {
  return `https://wa.me/${whatsappNumber(phone)}?text=${encodeURIComponent(text)}`
}

/** mailto link with subject and body; line breaks as CRLF, which mail apps expect. */
export function mailtoUrl(email: string, subject: string, body: string) {
  const crlf = body.replace(/\r\n/g, '\n').replace(/\n/g, '\r\n')
  return `mailto:${email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(crlf)}`
}
