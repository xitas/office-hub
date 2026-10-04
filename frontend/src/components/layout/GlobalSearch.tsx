import { useQuery } from '@tanstack/react-query'
import { Building2, FileText, MessageSquare, Search, SquareCheck, User, UsersRound, type LucideIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { api } from '@/lib/api'
import type { SearchHit } from '@/lib/types'
import { useDebouncedValue } from '@/lib/utils'

const GROUP_ICONS: Record<string, LucideIcon> = {
  users: User,
  departments: Building2,
  contacts: UsersRound,
  tasks: SquareCheck,
  messages: MessageSquare,
  files: FileText,
}

/** Ctrl/Cmd+K search across every module registered on the backend. */
export function GlobalSearch() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const debounced = useDebouncedValue(query.trim(), 250)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const { data, isFetching } = useQuery({
    queryKey: ['search', debounced],
    queryFn: async () =>
      (await api.get<{ results: Record<string, SearchHit[]> }>('/search/', { params: { q: debounced } })).data.results,
    enabled: open && debounced.length >= 2,
    staleTime: 30_000,
  })

  const go = (url: string) => {
    setOpen(false)
    setQuery('')
    navigate(url)
  }

  return (
    <>
      <Button
        variant="outline"
        className="hidden h-9 w-64 justify-start gap-2 text-muted-foreground md:flex lg:w-80"
        onClick={() => setOpen(true)}
      >
        <Search className="size-4" />
        <span className="flex-1 text-start">{t('search.button')}</span>
        <kbd className="rounded border bg-muted px-1.5 text-[10px] font-latin">Ctrl K</kbd>
      </Button>
      <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setOpen(true)} aria-label={t('common.search')}>
        <Search className="size-5" />
      </Button>

      <CommandDialog open={open} onOpenChange={setOpen} title={t('common.search')} description={t('search.placeholder')}>
        <Command shouldFilter={false}>
          <CommandInput value={query} onValueChange={setQuery} placeholder={t('search.placeholder')} />
          <CommandList>
            {debounced.length < 2 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">{t('search.typeMore')}</p>
            ) : (
              !isFetching && <CommandEmpty>{t('common.noResults')}</CommandEmpty>
            )}
            {debounced.length >= 2 &&
              Object.entries(data ?? {}).map(([group, hits]) => {
                const Icon = GROUP_ICONS[group] ?? Search
                return (
                  <CommandGroup key={group} heading={t(`search.groups.${group}`, { defaultValue: group })}>
                    {hits.map((hit) => (
                      <CommandItem key={`${group}-${hit.id}`} value={`${group}-${hit.id}`} onSelect={() => go(hit.url)}>
                        <Icon className="size-4" />
                        <div className="min-w-0">
                          <p className="truncate">{hit.title}</p>
                          {hit.subtitle && <p className="truncate text-xs text-muted-foreground">{hit.subtitle}</p>}
                        </div>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                )
              })}
          </CommandList>
        </Command>
      </CommandDialog>
    </>
  )
}
