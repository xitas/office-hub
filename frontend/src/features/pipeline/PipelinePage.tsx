import { List, SquareKanban } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/common'
import { Button } from '@/components/ui/button'
import { EMPTY_CONTACT_FILTERS, type ContactFilters } from '@/lib/contacts'
import type { ContactStatus } from '@/lib/types'
import { cn, useDebouncedValue } from '@/lib/utils'
import { ContactFilterBar, ContactResults } from '@/features/contacts/ContactBrowser'
import { PipelineBoard } from './PipelineBoard'

type View = 'board' | 'list'

/** Lead pipeline: a Kanban board of contacts by status, or the same contacts as a list. */
export function PipelinePage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const view: View = params.get('view') === 'list' ? 'list' : 'board'
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<ContactFilters>(EMPTY_CONTACT_FILTERS)
  const [page, setPage] = useState(1)
  const q = useDebouncedValue(search.trim())

  const setView = (next: View) => setParams(next === 'list' ? { view: 'list' } : {}, { replace: true })
  const showList = (status: ContactStatus) => {
    setFilters((f) => ({ ...f, status }))
    setPage(1)
    setView('list')
  }

  const toggle = (
    <div role="group" aria-label={t('pipeline.view')} className="inline-flex rounded-lg border bg-card p-0.5">
      {(
        [
          ['board', SquareKanban, t('pipeline.board')],
          ['list', List, t('pipeline.list')],
        ] as const
      ).map(([value, Icon, label]) => (
        <Button
          key={value}
          size="sm"
          variant="ghost"
          aria-pressed={view === value}
          onClick={() => setView(value)}
          className={cn('gap-1.5', view === value && 'bg-muted text-foreground')}
        >
          <Icon className="size-4" />
          {label}
        </Button>
      ))}
    </div>
  )

  return (
    <>
      <PageHeader title={t('pipeline.title')} subtitle={t('pipeline.subtitle')} actions={toggle} />
      <ContactFilterBar
        search={search}
        onSearch={(v) => {
          setSearch(v)
          setPage(1)
        }}
        filters={filters}
        onFilters={(f) => {
          setFilters(f)
          setPage(1)
        }}
        hide={view === 'board' ? ['status'] : []}
      />
      {view === 'board' ? (
        <PipelineBoard search={q} filters={filters} onShowList={showList} />
      ) : (
        <ContactResults search={q} filters={filters} page={page} onPage={setPage} />
      )}
    </>
  )
}
