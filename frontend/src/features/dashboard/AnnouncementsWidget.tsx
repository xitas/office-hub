import { Megaphone, Pin } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { EmptyState } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { textDir, type AnnouncementsWidget as WidgetData } from '@/lib/announcements'
import { useFormat } from '@/lib/format'

/** Current announcements I haven't opened yet: pinned first, then newest. */
export function AnnouncementsWidget({ data, loading, className }: { data: WidgetData | null | undefined; loading: boolean; className?: string }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  if (!loading && data === null) return null
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center gap-2">
        <Megaphone className="size-4 text-muted-foreground" />
        <CardTitle className="flex-1 text-sm font-medium">{t('dashboard.announcements')}</CardTitle>
        {!!data?.unread && (
          <Badge variant="secondary" className="font-latin">
            {fmt.number(data.unread)}
          </Badge>
        )}
        <Link to="/announcements" className="text-xs text-primary hover:underline">
          {t('dashboard.allAnnouncements')}
        </Link>
      </CardHeader>
      <CardContent>
        {loading || !data ? (
          <div className="space-y-2">
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
          </div>
        ) : !data.items.length ? (
          <EmptyState icon={Megaphone} title={t('dashboard.noAnnouncements')} className="py-4" />
        ) : (
          <ul className="divide-y">
            {data.items.map((item) => (
              <li key={item.id}>
                <Link to={item.url} className="flex items-start gap-2.5 py-2 text-sm hover:text-primary">
                  {item.pinned ? (
                    <Pin className="mt-0.5 size-4 shrink-0 text-primary" aria-label={t('announcements.pinnedBadge')} />
                  ) : (
                    <span className="mt-1.5 size-2 shrink-0 rounded-full bg-primary" />
                  )}
                  <span className="min-w-0 flex-1">
                    <span dir={textDir(item.title)} className="block truncate font-medium">{item.title}</span>
                    {item.preview && (
                      <span dir={textDir(item.preview)} className="block truncate text-xs text-muted-foreground">
                        {item.preview}
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">{fmt.relative(item.published_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
