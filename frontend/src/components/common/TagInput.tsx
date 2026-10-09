import { useQuery } from '@tanstack/react-query'
import { Plus, X } from 'lucide-react'
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { api } from '@/lib/api'
import type { Tag } from '@/lib/types'
import { cn, useDebouncedValue } from '@/lib/utils'

const MAX_TAGS = 20

/**
 * Tag picker: type to get suggestions from existing tags; Enter or comma adds the
 * typed text as a new tag (created on save). Duplicates are ignored regardless of case.
 */
export function TagInput({ id, value, onChange }: { id?: string; value: string[]; onChange: (tags: string[]) => void }) {
  const { t } = useTranslation()
  const listId = useId()
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const query = useDebouncedValue(text.trim(), 200)

  const { data: suggestions = [] } = useQuery({
    queryKey: ['tags', query],
    queryFn: async () => (await api.get<Tag[]>('/tags/', { params: { search: query || undefined } })).data,
    enabled: open,
    staleTime: 30_000,
  })

  const has = (name: string) => value.some((v) => v.toLocaleLowerCase() === name.toLocaleLowerCase())
  const add = (raw: string) => {
    const name = raw.replace(/,/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 50)
    if (name && !has(name) && value.length < MAX_TAGS) onChange([...value, name])
    setText('')
  }
  const remove = (name: string) => onChange(value.filter((v) => v !== name))
  const options = suggestions.filter((s) => !has(s.name)).slice(0, 8)
  const exact = options.some((s) => s.name.toLocaleLowerCase() === text.trim().toLocaleLowerCase())
  const showList = open && (options.length > 0 || (text.trim() !== '' && !exact))
  const listRef = useRef<HTMLUListElement>(null)

  // Near the bottom of the screen (e.g. in a long form) the list could open below the fold.
  useEffect(() => {
    if (showList) listRef.current?.scrollIntoView({ block: 'nearest' })
  }, [showList, options.length])

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      add(text)
    } else if (e.key === 'Backspace' && !text && value.length) {
      remove(value[value.length - 1])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="relative">
      <div
        className={cn(
          'flex min-h-8 flex-wrap items-center gap-1.5 rounded-lg border border-input bg-card px-2 py-1 dark:bg-input/30',
          'focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50',
        )}
      >
        {value.map((tag) => (
          <Badge key={tag} variant="secondary" className="gap-1 ps-2 pe-1">
            {tag}
            <button
              type="button"
              onClick={() => remove(tag)}
              className="rounded-sm p-0.5 hover:bg-foreground/10"
              aria-label={t('contacts.removeTag', { tag })}
            >
              <X className="size-3" />
            </button>
          </Badge>
        ))}
        <input
          id={id}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setOpen(true)
          }}
          onKeyDown={onKeyDown}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          placeholder={value.length ? '' : t('contacts.tagPlaceholder')}
          className="min-w-24 flex-1 bg-transparent py-0.5 text-sm outline-none placeholder:text-muted-foreground"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
        />
      </div>
      {showList && (
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          className="absolute inset-x-0 top-full z-50 mt-1 max-h-56 overflow-y-auto rounded-lg bg-popover p-1 text-sm shadow-md ring-1 ring-foreground/10"
        >
          {text.trim() && !exact && !has(text.trim()) && (
            <li>
              <button
                type="button"
                role="option"
                aria-selected={false}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => add(text)}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-start hover:bg-accent"
              >
                <Plus className="size-3.5" />
                {t('contacts.createTag', { tag: text.trim() })}
              </button>
            </li>
          )}
          {options.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                role="option"
                aria-selected={false}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => add(s.name)}
                className="w-full rounded-md px-2 py-1.5 text-start hover:bg-accent"
              >
                {s.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
