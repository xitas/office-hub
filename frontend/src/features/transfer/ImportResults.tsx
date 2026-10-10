import { AlertCircle, CheckCircle2, Download, Loader2, RefreshCw, SkipForward, Upload } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useFormat } from '@/lib/format'
import { downloadFile, importPath, OUTCOME_STYLES, type ImportJob } from '@/lib/transfer'
import { cn } from '@/lib/utils'

/** Step 3: progress while a background import runs, then the counts and every skipped/failed row. */
export function ImportResults({ job }: { job: ImportJob }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const [downloading, setDownloading] = useState(false)

  if (job.status === 'queued' || job.status === 'running') {
    const pct = job.total_rows ? Math.round((job.processed_rows / job.total_rows) * 100) : 0
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Loader2 className="size-4 animate-spin text-primary" />
            {t(job.status === 'queued' ? 'transfer.progress.queued' : 'transfer.progress.running')}
          </CardTitle>
          <CardDescription>{t('transfer.progress.hint')}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2">
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={job.total_rows}
            aria-valuenow={job.processed_rows}
            aria-label={t('transfer.progress.label')}
            className="h-2.5 overflow-hidden rounded-full bg-muted"
          >
            <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${pct}%` }} />
          </div>
          <p className="text-sm text-muted-foreground">
            {t('transfer.progress.count', { done: fmt.number(job.processed_rows), total: fmt.number(job.total_rows), pct })}
          </p>
        </CardContent>
      </Card>
    )
  }

  if (job.status === 'failed') {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
          <AlertCircle className="size-6 text-destructive" />
          <p className="font-medium">{t('transfer.crashed')}</p>
          <p className="max-w-md text-sm text-muted-foreground">{t('transfer.crashedHint')}</p>
          <Button nativeButton={false} render={<Link to={importPath(job.kind)} />}>
            <RefreshCw className="size-4" />
            {t('transfer.again')}
          </Button>
        </CardContent>
      </Card>
    )
  }

  const tiles = [
    { key: 'created', value: job.created, icon: CheckCircle2, style: 'text-success' },
    { key: 'updated', value: job.updated, icon: RefreshCw, style: 'text-primary' },
    { key: 'skipped', value: job.skipped, icon: SkipForward, style: 'text-muted-foreground' },
    { key: 'failed', value: job.failed, icon: AlertCircle, style: 'text-destructive' },
  ]

  const downloadFailed = async () => {
    setDownloading(true)
    try {
      await downloadFile(`/contact-imports/${job.id}/failed-rows/`, {}, 'failed-rows.csv')
    } catch {
      toast.error(t('transfer.exportFailed'))
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle>{t('transfer.results.title')}</CardTitle>
          <CardDescription>
            <bdi>{job.file_name}</bdi> · {t('transfer.rowCount', { count: job.total_rows })}
            {job.finished_at && ` · ${fmt.dateTime(job.finished_at)}`}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {tiles.map((tile) => (
              <div key={tile.key} className="rounded-lg border p-3">
                <div className={cn('flex items-center gap-1.5 text-sm', tile.style)}>
                  <tile.icon className="size-4" />
                  {t(`transfer.results.${tile.key}`)}
                </div>
                <p className="mt-1 text-2xl font-semibold font-latin">{fmt.number(tile.value)}</p>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button nativeButton={false} render={<Link to={`/${job.kind}`} />}>
              {t(`transfer.results.view.${job.kind}`)}
            </Button>
            <Button variant="outline" nativeButton={false} render={<Link to={importPath(job.kind)} />}>
              <Upload className="size-4" />
              {t('transfer.results.another')}
            </Button>
            {job.failed > 0 && (
              <Button variant="outline" onClick={() => void downloadFailed()} disabled={downloading}>
                {downloading ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
                {t('transfer.results.downloadFailed')}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {job.issue_count > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t('transfer.results.issues')}</CardTitle>
            {job.issue_count > job.issues.length && (
              <CardDescription>{t('transfer.results.issuesTruncated', { shown: job.issues.length, total: job.issue_count })}</CardDescription>
            )}
          </CardHeader>
          <CardContent className="px-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-14 ps-4">{t('transfer.preview.line')}</TableHead>
                  <TableHead className="w-28">{t('transfer.preview.result')}</TableHead>
                  <TableHead>{t('transfer.results.reason')}</TableHead>
                  <TableHead className="hidden md:table-cell">{t('transfer.results.values')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {job.issues.map((issue) => (
                  <TableRow key={issue.line} className="align-top">
                    <TableCell className="ps-4 text-muted-foreground font-latin">{issue.line}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={OUTCOME_STYLES[issue.outcome]}>
                        {t(`transfer.outcomes.${issue.outcome}`)}
                      </Badge>
                    </TableCell>
                    <TableCell className="min-w-48 whitespace-normal text-sm">
                      {/* Rendered in the reader's language by the server, so it follows the page direction. */}
                      <p>{issue.reason}</p>
                    </TableCell>
                    <TableCell className="hidden max-w-72 truncate text-xs text-muted-foreground md:table-cell" title={issue.values.join(', ')}>
                      <bdi>{issue.values.filter(Boolean).join(' · ')}</bdi>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
