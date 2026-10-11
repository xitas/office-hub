import { useQuery } from '@tanstack/react-query'
import { useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { UserAvatar } from '@/components/common'
import { Textarea } from '@/components/ui/textarea'
import { api } from '@/lib/api'
import type { MentionPerson } from '@/lib/tasks'
import { useDebouncedValue } from '@/lib/utils'
import { cn } from '@/lib/utils'

/** "@" followed by a few letters just before the caret. */
const TRIGGER = /(^|\s)@([^\s@]{0,30})$/

/** A textarea where typing "@" suggests people who can see the task. Picked people are kept in
 *  `mentions`; the text itself shows "@Full Name" and is turned into tokens when the comment is sent. */
export function MentionTextarea({
  id,
  taskId,
  value,
  onChange,
  mentions,
  onMentionsChange,
  placeholder,
  onSubmitShortcut,
  autoFocus,
}: {
  id: string
  taskId: number
  value: string
  onChange: (value: string) => void
  mentions: MentionPerson[]
  onMentionsChange: (people: MentionPerson[]) => void
  placeholder?: string
  /** Ctrl/Cmd+Enter */
  onSubmitShortcut?: () => void
  autoFocus?: boolean
}) {
  const { t } = useTranslation()
  const ref = useRef<HTMLTextAreaElement>(null)
  const [query, setQuery] = useState<string | null>(null)
  const [active, setActive] = useState(0)
  const q = useDebouncedValue(query ?? '', 150)

  const { data: people = [] } = useQuery({
    queryKey: ['tasks', 'people', taskId, q],
    queryFn: async () => (await api.get<MentionPerson[]>(`/tasks/${taskId}/people/`, { params: { q: q || undefined } })).data,
    enabled: query !== null,
    staleTime: 60_000,
  })
  const open = query !== null && people.length > 0

  const detect = (text: string, caret: number) => {
    const match = TRIGGER.exec(text.slice(0, caret))
    setQuery(match ? match[2] : null)
    setActive(0)
  }

  const choose = (person: MentionPerson) => {
    const el = ref.current
    if (!el) return
    const caret = el.selectionStart
    const before = value.slice(0, caret).replace(/@([^\s@]{0,30})$/, `@${person.full_name} `)
    const next = before + value.slice(caret)
    onChange(next)
    if (!mentions.some((m) => m.id === person.id)) onMentionsChange([...mentions, person])
    setQuery(null)
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(before.length, before.length)
    })
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (open) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActive((a) => (a + 1) % people.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActive((a) => (a - 1 + people.length) % people.length)
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        choose(people[active])
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setQuery(null)
        return
      }
    }
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && onSubmitShortcut) {
      e.preventDefault()
      onSubmitShortcut()
    }
  }

  return (
    <div className="relative">
      <Textarea
        ref={ref}
        id={id}
        value={value}
        rows={3}
        autoFocus={autoFocus}
        placeholder={placeholder}
        className="min-h-20"
        role="combobox"
        aria-expanded={open}
        aria-controls={`${id}-people`}
        aria-autocomplete="list"
        onChange={(e) => {
          onChange(e.target.value)
          detect(e.target.value, e.target.selectionStart)
        }}
        onKeyDown={onKeyDown}
        onBlur={() => setTimeout(() => setQuery(null), 150)}
      />
      {open && (
        <ul
          id={`${id}-people`}
          role="listbox"
          aria-label={t('tasks.comments.mentionSomeone')}
          // Opens above the box: the comment box sits at the end of the page.
          className="absolute start-0 bottom-full z-20 mb-1 max-h-56 w-64 overflow-y-auto rounded-lg border bg-popover p-1 text-sm shadow-md"
        >
          {people.map((p, i) => (
            <li key={p.id} role="option" aria-selected={i === active}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(p)}
                className={cn('flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-start', i === active ? 'bg-muted' : 'hover:bg-muted')}
              >
                <UserAvatar name={p.full_name} src={p.avatar} className="size-6" />
                <bdi className="truncate">{p.full_name}</bdi>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
