import { Check, ChevronDown, Search, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { UserAvatar } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useMe } from '@/lib/auth'
import type { TaskAssignee } from '@/lib/tasks'
import { useTaskAssignees } from '@/lib/tasks'
import { cn } from '@/lib/utils'

/** Pick one or more people. Offers yourself and your department (admins: everyone); people
 *  already on the task stay listed even if they're outside that group. */
export function AssigneePicker({
  id,
  value,
  onChange,
  current = [],
  invalid,
}: {
  id: string
  value: number[]
  onChange: (ids: number[]) => void
  /** Assignees already saved on the task (shown even if this user couldn't add them). */
  current?: TaskAssignee[]
  invalid?: boolean
}) {
  const { t } = useTranslation()
  const me = useMe()
  const options = useTaskAssignees()
  const [query, setQuery] = useState('')
  const people = [...options, ...current.filter((c) => !options.some((o) => o.id === c.id))]
  const byId = new Map(people.map((p) => [p.id, p]))
  const selected = value.map((v) => byId.get(v)).filter((p) => p !== undefined)
  const q = query.trim().toLowerCase()
  const shown = people.filter((p) => !q || p.full_name.toLowerCase().includes(q))

  const toggle = (pid: number) => onChange(value.includes(pid) ? value.filter((v) => v !== pid) : [...value, pid])
  const name = (p: { id: number; full_name: string }) => (p.id === me.id ? `${p.full_name} (${t('common.you')})` : p.full_name)

  return (
    <div className="grid gap-2">
      <Popover>
        <PopoverTrigger
          render={
            <Button
              id={id}
              type="button"
              variant="outline"
              aria-invalid={invalid}
              className="h-auto min-h-9 w-full justify-between gap-2 py-1.5 font-normal aria-invalid:border-destructive"
            />
          }
        >
          <span className={cn('truncate text-start', !selected.length && 'text-muted-foreground')}>
            {selected.length ? selected.map((p) => p.full_name).join(', ') : t('tasks.pickAssignees')}
          </span>
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
        </PopoverTrigger>
        <PopoverContent align="start" className="w-(--anchor-width) min-w-64 p-1.5">
          <div className="relative">
            <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('tasks.searchPeople')}
              aria-label={t('tasks.searchPeople')}
              className="h-8 ps-8"
            />
          </div>
          <ul role="listbox" aria-multiselectable="true" className="mt-1 max-h-64 overflow-y-auto">
            {shown.map((p) => {
              const on = value.includes(p.id)
              return (
                <li key={p.id} role="option" aria-selected={on}>
                  <button
                    type="button"
                    onClick={() => toggle(p.id)}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-start text-sm hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
                  >
                    <UserAvatar name={p.full_name} src={p.avatar} className="size-6" />
                    <span className="min-w-0 flex-1 truncate">
                      <bdi>{name(p)}</bdi>
                    </span>
                    <Check className={cn('size-4 text-primary', !on && 'invisible')} />
                  </button>
                </li>
              )
            })}
            {!shown.length && <li className="px-2 py-3 text-center text-sm text-muted-foreground">{t('common.noResults')}</li>}
          </ul>
        </PopoverContent>
      </Popover>
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((p) => (
            <span key={p.id} className="inline-flex items-center gap-1.5 rounded-full border bg-muted/40 py-0.5 ps-0.5 pe-1.5 text-xs">
              <UserAvatar name={p.full_name} src={p.avatar} className="size-5" />
              <bdi>{p.full_name}</bdi>
              <button
                type="button"
                onClick={() => toggle(p.id)}
                className="rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label={t('tasks.removeAssignee', { name: p.full_name })}
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
