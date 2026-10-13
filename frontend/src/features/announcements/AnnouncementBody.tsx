import { Fragment, type ReactNode } from 'react'
import { textDir } from '@/lib/announcements'
import { cn } from '@/lib/utils'

// [text](url) | **bold** | bare link. Only http(s) and mailto become links; anything else stays text.
const INLINE = /\[([^\]\n]{1,200})\]\(([^)\s]{1,500})\)|\*\*(.+?)\*\*|\b((?:https?:\/\/|www\.)[^\s<>"']+)/g
const SAFE = /^(https?:\/\/|mailto:)/i

function ExternalLink({ href, children, links }: { href: string; children: ReactNode; links: boolean }) {
  // Inside something that is already a link (a board card), links show as plain text.
  if (!links) return <span className="underline underline-offset-2">{children}</span>
  return (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-primary underline underline-offset-2 [overflow-wrap:anywhere]">
      {children}
    </a>
  )
}

function Inline({ text, links }: { text: string; links: boolean }) {
  const parts: ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(INLINE)) {
    const start = m.index ?? 0
    let end = start + m[0].length
    parts.push(<Fragment key={`t${start}`}>{text.slice(last, start)}</Fragment>)
    if (m[1] !== undefined) {
      parts.push(SAFE.test(m[2]) ? <ExternalLink key={start} href={m[2]} links={links}>{m[1]}</ExternalLink> : <Fragment key={start}>{m[0]}</Fragment>)
    } else if (m[3] !== undefined) {
      parts.push(<strong key={start} className="font-semibold"><Inline text={m[3]} links={links} /></strong>)
    } else {
      // Trailing punctuation belongs to the sentence, not the link.
      const url = m[4].replace(/[.,;:!?)\]]+$/, '')
      end = start + url.length
      parts.push(<ExternalLink key={start} href={url.toLowerCase().startsWith('www.') ? `https://${url}` : url} links={links}>{url}</ExternalLink>)
    }
    last = end
  }
  parts.push(<Fragment key="end">{text.slice(last)}</Fragment>)
  return <>{parts}</>
}

type Block = { kind: 'p'; lines: string[] } | { kind: 'ul' | 'ol'; items: string[] }

function blocks(body: string): Block[] {
  const out: Block[] = []
  for (const raw of body.replace(/\r\n/g, '\n').split('\n')) {
    const line = raw.trimEnd()
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line)
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    const prev = out[out.length - 1]
    if (bullet || numbered) {
      const kind = bullet ? 'ul' : 'ol'
      const item = (bullet ?? numbered)![1]
      if (prev?.kind === kind) prev.items.push(item)
      else out.push({ kind, items: [item] })
    } else if (!line.trim()) {
      out.push({ kind: 'p', lines: [] })
    } else if (prev?.kind === 'p' && prev.lines.length) {
      prev.lines.push(line)
    } else {
      out.push({ kind: 'p', lines: [line] })
    }
  }
  return out.filter((b) => (b.kind === 'p' ? b.lines.length > 0 : true))
}

/** An announcement's text with its light formatting (never rendered as HTML). Urdu text reads right to left. */
export function AnnouncementBody({ body, className, links = true }: { body: string; className?: string; links?: boolean }) {
  const dir = textDir(body)
  return (
    <div dir={dir} className={cn('space-y-2 text-sm leading-relaxed [overflow-wrap:anywhere]', dir === 'rtl' ? 'text-right' : 'text-left', className)}>
      {blocks(body).map((b, i) =>
        b.kind === 'p' ? (
          <p key={i}>
            {b.lines.map((line, j) => (
              <Fragment key={j}>
                {j > 0 && <br />}
                <Inline text={line} links={links} />
              </Fragment>
            ))}
          </p>
        ) : b.kind === 'ul' ? (
          <ul key={i} className="list-disc space-y-0.5 ps-5">
            {b.items.map((item, j) => (
              <li key={j}><Inline text={item} links={links} /></li>
            ))}
          </ul>
        ) : (
          <ol key={i} className="list-decimal space-y-0.5 ps-5">
            {b.items.map((item, j) => (
              <li key={j}><Inline text={item} links={links} /></li>
            ))}
          </ol>
        ),
      )}
    </div>
  )
}
