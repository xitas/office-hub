import { useQuery } from '@tanstack/react-query'
import { AlarmClock, Building2, CheckSquare, UserRound } from 'lucide-react'
import { Fragment, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { useFormat } from '@/lib/format'
import { cn } from '@/lib/utils'

const LINK = /\b((?:https?:\/\/|www\.)[^\s<>"']+)/gi
// Mention tokens and @channel / @here, in one pass.
const SPECIAL = /@\[([^\]\n]{1,150})\]\(user:(\d+)\)|(?<![\w@[])@(channel|here)\b/g
const RECORD_PATH = /^\/(tasks|contacts|companies)\/(\d+)\/?$/
const TYPES: Record<string, RecordType> = { tasks: 'task', contacts: 'contact', companies: 'company' }

type RecordType = 'task' | 'contact' | 'company'
interface RecordCard {
  type: RecordType
  id: number
  title: string
  url: string
  status: string | null
  status_label: string | null
  subtitle?: string
  due_date?: string | null
  is_overdue?: boolean
}

function escapeRegExp(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Plain text with search words highlighted. */
function Highlighted({ text, words }: { text: string; words?: string[] }) {
  const usable = (words ?? []).filter((w) => w.length > 0)
  if (!usable.length) return <>{text}</>
  const re = new RegExp(`(${usable.map(escapeRegExp).join('|')})`, 'gi')
  return (
    <>
      {text.split(re).map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="rounded-sm bg-amber-200 px-0.5 text-inherit dark:bg-amber-500/40">
            {part}
          </mark>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  )
}

/** A link inside the app (a task, contact or company) opens in place; other links in a new tab without opener or referrer. */
function SmartLink({ url, words }: { url: string; words?: string[] }) {
  const href = url.toLowerCase().startsWith('www.') ? `https://${url}` : url
  const inApp = appRecord(href)
  if (inApp) {
    return (
      <Link to={inApp.path} className="text-primary underline underline-offset-2 [overflow-wrap:anywhere]">
        <Highlighted text={url} words={words} />
      </Link>
    )
  }
  return (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-primary underline underline-offset-2 [overflow-wrap:anywhere]">
      <Highlighted text={url} words={words} />
    </a>
  )
}

function Linkified({ text, words, links = true }: { text: string; words?: string[]; links?: boolean }) {
  if (!links) return <Highlighted text={text} words={words} />
  const parts: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(LINK)) {
    let url = match[0]
    // Trailing punctuation belongs to the sentence, not the link.
    const trail = url.match(/[.,;:!?)\]]+$/)?.[0] ?? ''
    url = url.slice(0, url.length - trail.length)
    const start = match.index ?? 0
    parts.push(<Highlighted key={`t${start}`} text={text.slice(last, start)} words={words} />)
    parts.push(<SmartLink key={`l${start}`} url={url} words={words} />)
    last = start + url.length
  }
  parts.push(<Highlighted key="end" text={text.slice(last)} words={words} />)
  return <>{parts}</>
}

/** Message text: mentions as chips (stronger when it's you), @channel / @here highlighted, links clickable
 *  (`links={false}` inside something that is already a link, e.g. a search result). */
export function MessageText({ body, words, links = true }: { body: string; words?: string[]; links?: boolean }) {
  const me = useMe()
  const parts: ReactNode[] = []
  let last = 0
  for (const match of body.matchAll(SPECIAL)) {
    const start = match.index ?? 0
    parts.push(<Linkified key={`x${start}`} text={body.slice(last, start)} words={words} links={links} />)
    const broadcast = match[3]
    const isMe = !broadcast && Number(match[2]) === me.id
    parts.push(
      <bdi
        key={`m${start}`}
        className={cn(
          'rounded px-0.5 font-medium',
          broadcast || isMe ? 'bg-amber-200/70 text-amber-900 dark:bg-amber-500/25 dark:text-amber-200' : 'bg-primary/10 text-primary',
        )}
      >
        <Highlighted text={`@${broadcast ?? match[1]}`} words={words} />
      </bdi>,
    )
    last = start + match[0].length
  }
  parts.push(<Linkified key="rest" text={body.slice(last)} words={words} links={links} />)
  return <>{parts}</>
}

/** The task, contact or company a link points to, if it's a link into this app. */
function appRecord(href: string): { type: RecordType; id: number; path: string } | null {
  try {
    const url = new URL(href, window.location.origin)
    if (url.host !== window.location.host) return null
    const m = RECORD_PATH.exec(url.pathname)
    return m ? { type: TYPES[m[1]], id: Number(m[2]), path: url.pathname } : null
  } catch {
    return null
  }
}

/** Cards for links to records in the app, shown only when the viewer may see the record (otherwise just the link). */
export function RecordCards({ body }: { body: string }) {
  const records = new Map<string, { type: RecordType; id: number }>()
  for (const match of body.matchAll(LINK)) {
    const r = appRecord(match[0].replace(/[.,;:!?)\]]+$/, ''))
    if (r) records.set(`${r.type}:${r.id}`, r)
  }
  if (!records.size) return null
  return (
    <ul className="mt-1 flex flex-col gap-1.5">
      {[...records.values()].slice(0, 3).map((r) => (
        <Card key={`${r.type}:${r.id}`} type={r.type} id={r.id} />
      ))}
    </ul>
  )
}

const ICONS = { task: CheckSquare, contact: UserRound, company: Building2 }

function Card({ type, id }: { type: RecordType; id: number }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const { data } = useQuery({
    queryKey: ['chat', 'record-card', type, id],
    queryFn: async () => (await api.get<RecordCard>('/chat/record-card/', { params: { type, id } })).data,
    retry: false,
    staleTime: 60_000,
  })
  if (!data) return null
  const Icon = ICONS[type]
  return (
    <li>
      <Link
        to={data.url}
        className="flex max-w-sm items-center gap-2.5 rounded-md border bg-card px-2.5 py-2 text-sm shadow-xs hover:bg-muted"
        aria-label={t('chat.recordCard', { type: t(`chat.recordTypes.${type}`), title: data.title })}
      >
        <Icon className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1">
          <bdi className="block truncate font-medium">{data.title}</bdi>
          <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
            <span>{t(`chat.recordTypes.${type}`)}</span>
            {data.status_label && <span>· {data.status_label}</span>}
            {data.subtitle && (
              <span className="truncate">
                · <bdi>{data.subtitle}</bdi>
              </span>
            )}
            {data.due_date && (
              <span className={cn('inline-flex items-center gap-1', data.is_overdue && 'font-medium text-destructive')}>
                · <AlarmClock className="size-3" />
                <bdi className="font-latin">{fmt.date(`${data.due_date}T12:00:00`)}</bdi>
              </span>
            )}
          </span>
        </span>
      </Link>
    </li>
  )
}
