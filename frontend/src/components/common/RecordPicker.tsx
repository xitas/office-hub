import { useQuery } from '@tanstack/react-query'
import { Building2, Search } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { UserAvatar } from '@/components/common'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import type { TimelineTarget } from '@/lib/timeline'
import type { Company, Contact, Paginated } from '@/lib/types'
import { useDebouncedValue } from '@/lib/useDebouncedValue'

/** A contact or company chosen in the picker (only records the user can see are offered). */
export interface Picked {
  target: TimelineTarget
  name: string
  hint: string
  type: 'contact' | 'company'
}

const LIMIT = 6

/** Search contacts and companies the user can see, and pick one. */
export function RecordPicker({ onPick, idPrefix = 'quick-note' }: { onPick: (picked: Picked) => void; idPrefix?: string }) {
  const { t } = useTranslation()
  const [search, setSearch] = useState('')
  const q = useDebouncedValue(search.trim(), 250)

  const { data, isFetching } = useQuery({
    queryKey: ['timeline', 'picker', q],
    queryFn: async () => {
      const params = { search: q, page_size: LIMIT }
      const [contacts, companies] = await Promise.all([
        api.get<Paginated<Contact>>('/contacts/', { params: { ...params, ordering: '-updated_at' } }),
        api.get<Paginated<Company>>('/companies/', { params: { ...params, ordering: '-updated_at' } }),
      ])
      return { contacts: contacts.data.results, companies: companies.data.results }
    },
    placeholderData: (prev) => prev,
  })

  const empty = data && !data.contacts.length && !data.companies.length

  return (
    <div className="grid gap-3">
      <Label htmlFor={`${idPrefix}-search`}>{t('timeline.pickRecord')}</Label>
      <div className="relative">
        <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          id={`${idPrefix}-search`}
          autoFocus
          value={search}
          placeholder={t('timeline.pickPlaceholder')}
          onChange={(e) => setSearch(e.target.value)}
          className="ps-8"
        />
      </div>
      <div className={isFetching ? 'opacity-60 transition-opacity' : undefined}>
        {empty ? (
          <p className="py-6 text-center text-sm text-muted-foreground">{t('common.noResults')}</p>
        ) : (
          <div className="grid gap-3">
            {!!data?.contacts.length && (
              <PickList
                title={t('contacts.title')}
                items={data.contacts.map((c) => ({
                  target: { contact: c.id },
                  name: c.full_name,
                  hint: [c.company_name, c.city].filter(Boolean).join(' · '),
                  type: 'contact' as const,
                }))}
                onPick={onPick}
              />
            )}
            {!!data?.companies.length && (
              <PickList
                title={t('companies.title')}
                items={data.companies.map((c) => ({
                  target: { company: c.id },
                  name: c.name,
                  hint: [c.industry_label, c.city].filter(Boolean).join(' · '),
                  type: 'company' as const,
                }))}
                onPick={onPick}
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function PickList({ title, items, onPick }: { title: string; items: Picked[]; onPick: (p: Picked) => void }) {
  return (
    <div>
      <p className="mb-1 px-1 text-xs font-medium text-muted-foreground">{title}</p>
      <ul className="divide-y rounded-lg border">
        {items.map((item) => (
          <li key={`${item.type}-${'contact' in item.target ? item.target.contact : item.target.company}`}>
            <button
              type="button"
              onClick={() => onPick(item)}
              className="flex w-full items-center gap-3 px-3 py-2 text-start transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none"
            >
              {item.type === 'contact' ? (
                <UserAvatar name={item.name} className="size-7" />
              ) : (
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted">
                  <Building2 className="size-3.5 text-muted-foreground" />
                </span>
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm">{item.name}</span>
                {item.hint && <span className="block truncate text-xs text-muted-foreground">{item.hint}</span>}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
