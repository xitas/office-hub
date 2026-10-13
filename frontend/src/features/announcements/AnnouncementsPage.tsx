import { Archive, Megaphone, Paperclip, Pin, Plus, Search } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { EmptyState, ErrorState, PageHeader, Pagination } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { textDir, useAnnouncements, type Announcement } from '@/lib/announcements'
import { useFormat } from '@/lib/format'
import { usePermission } from '@/lib/permissions'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { cn } from '@/lib/utils'
import { AnnouncementBody } from './AnnouncementBody'
import { AnnouncementEditor } from './AnnouncementEditor'

/** The announcements board: pinned first, then newest. Expired announcements are under "Archive". */
export function AnnouncementsPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const archive = params.get('tab') === 'archive'
  const page = Number(params.get('page') ?? 1) || 1
  const [search, setSearch] = useState(params.get('q') ?? '')
  const q = useDebouncedValue(search.trim(), 250)
  const [creating, setCreating] = useState(false)
  const canPost = usePermission('announcements.create')
  const { data, isLoading, isError, refetch } = useAnnouncements({ archive, q, page })
  const set = (changes: Record<string, string>) =>
    setParams((p) => {
      for (const [k, v] of Object.entries(changes)) {
        if (v) p.set(k, v)
        else p.delete(k)
      }
      return p
    }, { replace: true })

  return (
    <>
      <PageHeader
        title={t('announcements.title')}
        subtitle={t('announcements.subtitle')}
        actions={
          canPost && (
            <Button onClick={() => setCreating(true)}>
              <Plus className="size-4" />
              {t('announcements.new')}
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs value={archive ? 'archive' : 'current'} onValueChange={(v) => set({ tab: v === 'archive' ? 'archive' : '', page: '' })}>
          <TabsList>
            <TabsTrigger value="current">
              <Megaphone className="size-4" />
              {t('announcements.current')}
            </TabsTrigger>
            <TabsTrigger value="archive">
              <Archive className="size-4" />
              {t('announcements.archive')}
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <label className="flex min-w-0 flex-1 items-center gap-2 rounded-md border bg-background px-2 sm:max-w-xs">
          <Search className="size-4 text-muted-foreground" />
          <input
            type="search"
            value={search}
            dir="auto"
            onChange={(e) => {
              setSearch(e.target.value)
              set({ q: e.target.value.trim(), page: '' })
            }}
            placeholder={t('announcements.search')}
            aria-label={t('announcements.search')}
            className="h-9 min-w-0 flex-1 bg-transparent text-sm outline-none"
          />
        </label>
      </div>

      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading ? (
        <div className="grid gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-36 rounded-xl" />
          ))}
        </div>
      ) : !data?.results.length ? (
        <EmptyState
          icon={archive ? Archive : Megaphone}
          title={q ? t('announcements.noMatches') : archive ? t('announcements.archiveEmpty') : t('announcements.empty')}
          hint={archive || q ? undefined : t('announcements.emptyHint')}
          className="py-16"
        />
      ) : (
        <>
          <ul className="grid gap-3">
            {data.results.map((a) => (
              <AnnouncementCard key={a.id} announcement={a} />
            ))}
          </ul>
          <Pagination page={page} count={data.count} onPage={(p) => set({ page: p > 1 ? String(p) : '' })} />
        </>
      )}
      {creating && <AnnouncementEditor onClose={() => setCreating(false)} />}
    </>
  )
}

function AnnouncementCard({ announcement: a }: { announcement: Announcement }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const dir = textDir(a.title)
  return (
    <li>
      <Link to={`/announcements/${a.id}`} className="block rounded-xl focus-visible:ring-2 focus-visible:ring-ring">
        <Card className={cn('gap-2 py-4 transition-colors hover:bg-muted/30', a.pinned && !a.expired && 'border-primary/40 bg-primary/[0.03]')}>
          <CardContent className="grid gap-2">
            <div className="flex items-start gap-2">
              {/* The unread dot stays beside the title, also when an Urdu title reads right to left in an English page. */}
              <div dir={dir} className="flex min-w-0 flex-1 items-start gap-2">
                {!a.is_read && <span className="mt-2 size-2 shrink-0 rounded-full bg-primary" aria-label={t('announcements.unread')} />}
                <h2 className={cn('min-w-0 flex-1 text-base', a.is_read ? 'font-medium' : 'font-semibold')}>{a.title}</h2>
              </div>
              {a.pinned && !a.expired && (
                <Badge variant="secondary" className="shrink-0 gap-1 font-normal">
                  <Pin className="size-3" />
                  {t('announcements.pinnedBadge')}
                </Badge>
              )}
            </div>
            <div className="relative max-h-24 overflow-hidden text-muted-foreground [mask-image:linear-gradient(to_bottom,black_60%,transparent)]">
              <AnnouncementBody body={a.body} links={false} />
            </div>
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              {a.created_by_name && <bdi className="font-medium text-foreground/80">{a.created_by_name}</bdi>}
              <span>· {fmt.relative(a.published_at)}</span>
              <span>· {a.audience === 'everyone' ? t('announcements.audiences.everyone') : a.department_names.join(', ')}</span>
              {a.attachments.length > 0 && (
                <span className="inline-flex items-center gap-1">
                  · <Paperclip className="size-3" />
                  <span className="font-latin">{a.attachments.length}</span>
                </span>
              )}
              {a.expires_on && (
                <span>· {t(a.expired ? 'announcements.expiredOn' : 'announcements.until', { date: fmt.date(`${a.expires_on}T12:00:00`) })}</span>
              )}
              {a.receipts && (
                <span className="ms-auto font-medium text-foreground/80">
                  {t('announcements.readBy', { read: fmt.number(a.receipts.read), total: fmt.number(a.receipts.total) })}
                </span>
              )}
            </p>
          </CardContent>
        </Card>
      </Link>
    </li>
  )
}
