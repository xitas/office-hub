import { useQuery } from '@tanstack/react-query'
import { Activity, CheckCircle2, CircleSlash, Clock, Database, RefreshCw, Server, XCircle, Zap, type LucideIcon } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ErrorState, PageHeader } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

type Check = { ok: boolean | null; [key: string]: unknown }
interface HealthReport {
  status: 'ok' | 'degraded'
  checks: Record<'database' | 'redis' | 'celery_workers' | 'celery_beat' | 'channels', Check>
}

const ROWS: { key: keyof HealthReport['checks']; icon: LucideIcon }[] = [
  { key: 'database', icon: Database },
  { key: 'redis', icon: Server },
  { key: 'celery_workers', icon: Zap },
  { key: 'celery_beat', icon: Clock },
  { key: 'channels', icon: Activity },
]

function StatusIcon({ ok }: { ok: boolean | null }) {
  if (ok === true) return <CheckCircle2 className="size-5 text-success" />
  if (ok === false) return <XCircle className="size-5 text-destructive" />
  return <CircleSlash className="size-5 text-muted-foreground" />
}

function detail(key: string, check: Check, t: (k: string, o?: Record<string, unknown>) => string): string {
  if (check.error) return t('admin.system.error', { error: String(check.error) })
  switch (key) {
    case 'database':
      return String(check.vendor ?? '')
    case 'redis':
      return check.configured === false ? t('admin.system.redisOff') : t('admin.system.latency', { ms: check.latency_ms })
    case 'celery_workers':
      if (check.mode === 'eager') return t('admin.system.eager')
      return (check.workers as string[] | undefined)?.length
        ? (check.workers as string[]).join(', ')
        : t('admin.system.noWorkers')
    case 'celery_beat':
      if (check.ok === null) return t('admin.system.eager')
      return check.last_heartbeat_seconds_ago == null
        ? t('admin.system.noHeartbeat')
        : t('admin.system.heartbeat', { seconds: check.last_heartbeat_seconds_ago })
    case 'channels':
      return String(check.backend ?? '')
    default:
      return ''
  }
}

export function SystemHealthPage() {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['system-health'],
    queryFn: async () => (await api.get<HealthReport>('/system/health/')).data,
    refetchInterval: 15_000,
  })

  return (
    <>
      <PageHeader
        title={t('admin.system.title')}
        subtitle={t('admin.system.subtitle')}
        actions={
          <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
            <RefreshCw className={cn('size-4', isFetching && 'animate-spin')} />
            {t('admin.system.refresh')}
          </Button>
        }
      />
      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading || !data ? (
        <Skeleton className="h-80 max-w-2xl rounded-xl" />
      ) : (
        <Card className="max-w-2xl py-0">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <span className="text-sm font-medium">{t('admin.system.overall')}</span>
            <Badge
              variant="outline"
              className={data.status === 'ok' ? 'border-success/40 text-success' : 'border-destructive/40 text-destructive'}
            >
              {t(`admin.system.status.${data.status}`)}
            </Badge>
          </div>
          <CardContent className="divide-y px-0">
            {ROWS.map(({ key, icon: Icon }) => {
              const check = data.checks[key]
              return (
                <div key={key} className="flex items-center gap-3 px-4 py-3">
                  <Icon className="size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{t(`admin.system.checks.${key}`)}</p>
                    <p className="truncate text-xs text-muted-foreground font-latin">{detail(key, check, t)}</p>
                  </div>
                  <StatusIcon ok={check.ok} />
                </div>
              )
            })}
          </CardContent>
        </Card>
      )}
    </>
  )
}
