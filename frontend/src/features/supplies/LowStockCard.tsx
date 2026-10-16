import { PackageOpen } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { itemName, useSupplyItems } from '@/lib/supplies'

/** Supplies at or below their reorder level (managers and admins). Loaded on its own, not part of /dashboard/. */
export function LowStockCard({ className }: { className?: string }) {
  const { t, i18n } = useTranslation()
  const { data, isLoading } = useSupplyItems({ low: true })
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center gap-2">
        <PackageOpen className="size-4 text-muted-foreground" />
        <CardTitle className="flex-1 text-sm font-medium">{t('supplies.lowStock')}</CardTitle>
        {!!data?.length && <Badge variant="outline" className="border-amber-500/50 font-latin text-amber-700 dark:text-amber-300">{data.length}</Badge>}
        <Link to="/supplies" className="text-xs text-primary hover:underline">{t('supplies.open')}</Link>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-16" />
        ) : !data?.length ? (
          <p className="text-sm text-muted-foreground">{t('supplies.allStocked')}</p>
        ) : (
          <ul className="grid gap-1.5">
            {data.slice(0, 6).map((item) => (
              <li key={item.id}>
                <Link to={`/supplies?item=${item.id}`} className="flex items-center gap-2 rounded-md px-1 py-0.5 text-sm hover:bg-muted">
                  <span className="min-w-0 flex-1 truncate">{itemName(item, i18n.language)}</span>
                  <span className="text-muted-foreground">
                    <span className="font-latin font-medium text-amber-700 dark:text-amber-300">{item.quantity}</span> <bdi>{item.unit}</bdi>
                  </span>
                  {item.open_requests > 0 && <Badge variant="secondary" className="font-normal">{t('supplies.requested')}</Badge>}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
