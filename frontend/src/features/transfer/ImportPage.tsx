import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, Building2, Download, FileSpreadsheet, Loader2, Upload, UsersRound } from 'lucide-react'
import { useState, type DragEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, PageHeader } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { api, apiError } from '@/lib/api'
import { useFormat } from '@/lib/format'
import { downloadFile, IMPORT_LIMITS, importPath, type ImportJob, type ImportKind, type ImportSummary } from '@/lib/transfer'
import { cn } from '@/lib/utils'
import { ImportResults } from './ImportResults'
import { ImportSetup } from './ImportSetup'

const STEPS = ['upload', 'match', 'results'] as const

/** CSV import: upload → match columns, options and preview → progress and results. */
export function ImportPage() {
  const { t } = useTranslation()
  const { id } = useParams()
  const { pathname } = useLocation()
  const kind: ImportKind = pathname.startsWith('/companies') ? 'companies' : 'contacts'

  const job = useQuery({
    queryKey: ['imports', Number(id)],
    queryFn: async () => (await api.get<ImportJob>(`/contact-imports/${id}/`)).data,
    enabled: !!id,
    retry: false,
    // Poll while a background import runs.
    refetchInterval: (q) => (q.state.data && ['queued', 'running'].includes(q.state.data.status) ? 1000 : false),
  })

  const step = !id ? 0 : job.data?.status === 'uploaded' ? 1 : 2
  const listPath = `/${job.data?.kind ?? kind}`

  return (
    <div className="max-w-5xl">
      <Button variant="ghost" size="sm" className="-ms-2 mb-3" nativeButton={false} render={<Link to={listPath} />}>
        <ArrowLeft className="size-4 rtl:rotate-180" />
        {t(job.data?.kind === 'companies' || (!id && kind === 'companies') ? 'companies.back' : 'contacts.back')}
      </Button>
      <PageHeader title={t(`transfer.title.${job.data?.kind ?? kind}`)} subtitle={t('transfer.subtitle')} />
      <Steps current={step} />
      {!id ? (
        <UploadStep kind={kind} />
      ) : job.isLoading ? (
        <Skeleton className="h-80 rounded-xl" />
      ) : job.isError || !job.data ? (
        <ErrorState onRetry={() => void job.refetch()} message={t('transfer.notFound')} />
      ) : job.data.status === 'uploaded' ? (
        <ImportSetup job={job.data} />
      ) : (
        <ImportResults job={job.data} />
      )}
    </div>
  )
}

function Steps({ current }: { current: number }) {
  const { t } = useTranslation()
  return (
    <ol className="mb-5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm" aria-label={t('transfer.steps.label')}>
      {STEPS.map((s, i) => (
        <li key={s} className="flex items-center gap-2" aria-current={i === current ? 'step' : undefined}>
          {i > 0 && <span aria-hidden className="h-px w-6 bg-border" />}
          <span
            className={cn(
              'flex size-6 items-center justify-center rounded-full border text-xs font-medium font-latin',
              i < current && 'border-primary bg-primary/10 text-primary',
              i === current && 'border-primary bg-primary text-primary-foreground',
              i > current && 'text-muted-foreground',
            )}
          >
            {i + 1}
          </span>
          <span className={i === current ? 'font-medium' : 'text-muted-foreground'}>{t(`transfer.steps.${s}`)}</span>
        </li>
      ))}
    </ol>
  )
}

function UploadStep({ kind }: { kind: ImportKind }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState('')

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData()
      body.append('file', file)
      body.append('kind', kind)
      return (await api.post<ImportJob>('/contact-imports/', body)).data
    },
    onSuccess: (job) => navigate(importPath(job.kind, job.id)),
    onError: (err) => {
      const info = apiError(err)
      setError(info.fields.file ?? info.message)
    },
  })

  const pick = (file: File | undefined) => {
    setError('')
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.csv')) return setError(t('transfer.notCsv'))
    if (file.size > IMPORT_LIMITS.megabytes * 1024 * 1024) return setError(t('transfer.tooLarge', { mb: IMPORT_LIMITS.megabytes }))
    upload.mutate(file)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    pick(e.dataTransfer.files[0])
  }

  const template = async () => {
    try {
      await downloadFile('/contact-imports/template/', { kind }, `${kind}-import-template.csv`)
    } catch {
      toast.error(t('transfer.exportFailed'))
    }
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap gap-2" role="tablist" aria-label={t('transfer.whatToImport')}>
        {(['contacts', 'companies'] as const).map((k) => {
          const Icon = k === 'contacts' ? UsersRound : Building2
          return (
            <Button
              key={k}
              role="tab"
              aria-selected={k === kind}
              variant={k === kind ? 'default' : 'outline'}
              size="sm"
              nativeButton={false}
              render={<Link to={importPath(k)} replace />}
            >
              <Icon className="size-4" />
              {t(`transfer.kinds.${k}`)}
            </Button>
          )
        })}
      </div>

      <Card>
        <CardContent className="grid gap-4">
          <label
            htmlFor="import-file"
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={cn(
              'flex cursor-pointer flex-col items-center gap-3 rounded-xl border-2 border-dashed px-4 py-10 text-center transition-colors',
              dragging ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/40',
              upload.isPending && 'pointer-events-none opacity-70',
            )}
          >
            <span className="rounded-full bg-primary/10 p-3 text-primary">
              {upload.isPending ? <Loader2 className="size-6 animate-spin" /> : <Upload className="size-6" />}
            </span>
            <span className="font-medium">{upload.isPending ? t('transfer.uploading') : t('transfer.dropHere')}</span>
            <span className="text-sm text-muted-foreground">
              {t('transfer.limits', { mb: IMPORT_LIMITS.megabytes, rows: IMPORT_LIMITS.rows.toLocaleString('en') })}
            </span>
            <input
              id="import-file"
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              onChange={(e) => {
                pick(e.target.files?.[0])
                e.target.value = ''
              }}
            />
          </label>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <div className="flex flex-col gap-3 rounded-lg bg-muted/50 p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
            <div className="flex gap-2">
              <FileSpreadsheet className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <p className="text-muted-foreground">{t('transfer.excelHint')}</p>
            </div>
            <Button variant="outline" size="sm" className="shrink-0" onClick={() => void template()}>
              <Download className="size-4" />
              {t('transfer.template')}
            </Button>
          </div>
        </CardContent>
      </Card>

      <RecentImports />
    </div>
  )
}

function RecentImports() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const { data } = useQuery({
    queryKey: ['imports', 'recent'],
    queryFn: async () => (await api.get<ImportSummary[]>('/contact-imports/')).data,
  })
  if (!data) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('transfer.recent')}</CardTitle>
      </CardHeader>
      <CardContent className="px-0">
        {!data.length ? (
          <EmptyState icon={FileSpreadsheet} title={t('transfer.noRecent')} className="py-4" />
        ) : (
          <ul className="divide-y">
            {data.map((job) => (
              <li key={job.id}>
                <Link to={importPath(job.kind, job.id)} className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-muted/50">
                  <FileSpreadsheet className="size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      <bdi>{job.file_name}</bdi>
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {t(`transfer.kinds.${job.kind}`)} · {fmt.dateTime(job.created_at)}
                      {job.status === 'done' && ` · ${t('transfer.recentCounts', { created: job.created, updated: job.updated, failed: job.failed })}`}
                    </p>
                  </div>
                  <Badge variant="outline" className="shrink-0">
                    {t(`transfer.statuses.${job.status}`)}
                  </Badge>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
