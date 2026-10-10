import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ArrowRight, Loader2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { FormField, SimpleSelect } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api, apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { useAssignableUsers } from '@/lib/companies'
import { importPath, OUTCOME_STYLES, type DuplicateMode, type ImportJob, type PreviewRow } from '@/lib/transfer'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { cn } from '@/lib/utils'

const SKIP = '__skip__'
const MODES: DuplicateMode[] = ['skip', 'update', 'create']

/** Step 2: match file columns to fields, choose options, check the preview, then run. */
export function ImportSetup({ job }: { job: ImportJob }) {
  const { t } = useTranslation()
  const me = useMe()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const assignable = useAssignableUsers()
  const [mapping, setMapping] = useState<Record<string, string>>(job.mapping)
  const [duplicates, setDuplicates] = useState<DuplicateMode>(job.options.duplicates ?? 'skip')
  const [createCompanies, setCreateCompanies] = useState(job.options.create_companies ?? true)
  const [assignTo, setAssignTo] = useState(String(job.options.assign_to ?? me.id))
  const [runError, setRunError] = useState('')

  const settings = useMemo(
    () => ({ mapping, duplicates, create_companies: createCompanies, assign_to: Number(assignTo) }),
    [mapping, duplicates, createCompanies, assignTo],
  )
  // Re-check the preview shortly after the mapping or options change.
  const debounced = useDebouncedValue(JSON.stringify(settings), 300)
  const preview = useQuery({
    queryKey: ['imports', job.id, 'preview', debounced],
    queryFn: async () =>
      (await api.post<{ rows: PreviewRow[]; total_rows: number }>(`/contact-imports/${job.id}/preview/`, JSON.parse(debounced))).data,
    placeholderData: keepPreviousData,
    retry: false,
  })
  const previewError = preview.isError ? apiError(preview.error) : null

  const run = useMutation({
    mutationFn: async () => (await api.post<ImportJob>(`/contact-imports/${job.id}/run/`, settings)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(['imports', job.id], data)
      void queryClient.invalidateQueries({ queryKey: [job.kind] })
      void queryClient.invalidateQueries({ queryKey: ['imports', 'recent'] })
      navigate(importPath(data.kind, data.id), { replace: true })
    },
    onError: (err) => {
      const info = apiError(err)
      setRunError(Object.values(info.fields)[0] ?? info.message)
    },
  })

  const fieldLabel = (key: string) => job.fields.find((f) => f.key === key)?.label ?? key
  const used = new Set(Object.values(mapping))
  const mappedKeys = job.fields.map((f) => f.key).filter((k) => used.has(k))
  const required = job.fields.filter((f) => f.required)
  const missingRequired =
    job.kind === 'contacts' ? !used.has('first_name') && !used.has('full_name') : required.some((f) => !used.has(f.key))

  const setColumn = (index: number, key: string) =>
    setMapping((m) => {
      const next = { ...m }
      if (key === SKIP) delete next[String(index)]
      else next[String(index)] = key
      return next
    })

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle>{t('transfer.match.title')}</CardTitle>
          <CardDescription>
            <bdi>{job.file_name}</bdi> · {t('transfer.rowCount', { count: job.total_rows })}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="hidden grid-cols-[minmax(0,1fr)_minmax(0,1fr)_15rem] gap-4 px-1 text-xs font-medium text-muted-foreground md:grid">
            <span>{t('transfer.match.column')}</span>
            <span>{t('transfer.match.sample')}</span>
            <span>{t('transfer.match.field')}</span>
          </div>
          <ul className="grid gap-3 md:gap-2">
            {job.headers.map((header, index) => {
              const current = mapping[String(index)] ?? SKIP
              const samples = job.sample.map((row) => row[index]).filter(Boolean).slice(0, 2)
              return (
                <li
                  key={index}
                  className="grid gap-2 rounded-lg border p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_15rem] md:items-center md:gap-4 md:border-0 md:p-1"
                >
                  <span className="truncate text-sm font-medium" title={header}>
                    <bdi>{header}</bdi>
                  </span>
                  <span className="truncate text-sm text-muted-foreground" title={samples.join(' · ')}>
                    {samples.length ? <bdi>{samples.join(' · ')}</bdi> : t('transfer.match.empty')}
                  </span>
                  <SimpleSelect
                    id={`map-${index}`}
                    value={current}
                    onChange={(v) => setColumn(index, v)}
                    className={cn(current === SKIP && 'text-muted-foreground')}
                    options={[
                      { value: SKIP, label: t('transfer.match.skip') },
                      // Fields already matched to another column are left out.
                      ...job.fields
                        .filter((f) => f.key === current || !used.has(f.key))
                        .map((f) => ({ value: f.key, label: f.required ? `${f.label} *` : f.label })),
                    ]}
                  />
                </li>
              )
            })}
          </ul>
          {missingRequired && (
            <p className="flex items-center gap-1.5 text-sm text-destructive">
              <AlertCircle className="size-4" />
              {t(job.kind === 'contacts' ? 'transfer.match.needName' : 'transfer.match.needCompanyName')}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('transfer.options.title')}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-5">
          <fieldset className="grid gap-2">
            <legend className="mb-2 text-sm font-medium">
              {t(job.kind === 'contacts' ? 'transfer.options.duplicates' : 'transfer.options.duplicatesCompanies')}
            </legend>
            <div className="grid gap-2 sm:grid-cols-3">
              {MODES.map((mode) => (
                <label
                  key={mode}
                  className={cn(
                    'flex cursor-pointer gap-2.5 rounded-lg border p-3 text-sm transition-colors has-focus-visible:ring-3 has-focus-visible:ring-ring/50',
                    duplicates === mode ? 'border-primary bg-primary/5' : 'hover:bg-muted/40',
                  )}
                >
                  <input
                    type="radio"
                    name="duplicates"
                    value={mode}
                    checked={duplicates === mode}
                    onChange={() => setDuplicates(mode)}
                    className="mt-0.5 size-4 accent-primary"
                  />
                  <span>
                    <span className="block font-medium">{t(`transfer.options.modes.${mode}`)}</span>
                    <span className="block text-xs text-muted-foreground">{t(`transfer.options.modeHints.${job.kind}.${mode}`)}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="grid gap-4 sm:grid-cols-2">
            {job.kind === 'contacts' && (
              <div className="flex items-start gap-2.5">
                <Checkbox
                  id="create-companies"
                  checked={createCompanies}
                  onCheckedChange={(v) => setCreateCompanies(v === true)}
                  className="mt-0.5"
                />
                <div className="grid gap-0.5">
                  <Label htmlFor="create-companies">{t('transfer.options.createCompanies')}</Label>
                  <p className="text-xs text-muted-foreground">{t('transfer.options.createCompaniesHint')}</p>
                </div>
              </div>
            )}
            {assignable ? (
              <FormField id="assign-to" label={t('transfer.options.assignTo')} hint={t('transfer.options.assignToHint')}>
                <SimpleSelect
                  id="assign-to"
                  value={assignTo}
                  onChange={setAssignTo}
                  options={assignable.map((u) => ({ value: String(u.id), label: u.id === me.id ? `${u.full_name} (${t('common.you')})` : u.full_name }))}
                />
              </FormField>
            ) : (
              <p className="text-sm text-muted-foreground">{t('transfer.options.assignedToYou')}</p>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {t('transfer.preview.title')}
            {preview.isFetching && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
          </CardTitle>
          <CardDescription>
            {t('transfer.preview.hint', { count: Math.min(10, job.total_rows) })}
            {duplicates === 'update' && ` ${t('transfer.preview.updateLegend')}`}
          </CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          {previewError ? (
            <p className="px-4 text-sm text-destructive">{Object.values(previewError.fields)[0] ?? previewError.message}</p>
          ) : !preview.data ? (
            <div className="space-y-2 px-4">
              <Skeleton className="h-9" />
              <Skeleton className="h-9" />
            </div>
          ) : (
            <PreviewTable rows={preview.data.rows} keys={mappedKeys} label={fieldLabel} />
          )}
        </CardContent>
        <CardFooter className="flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground">
            {job.total_rows > 300 ? t('transfer.backgroundHint') : t('transfer.rowCount', { count: job.total_rows })}
          </p>
          <Button onClick={() => run.mutate()} disabled={run.isPending || missingRequired || !!previewError}>
            {run.isPending ? <Loader2 className="size-4 animate-spin" /> : <ArrowRight className="size-4 rtl:rotate-180" />}
            {run.isPending ? t('transfer.importing') : t('transfer.run', { count: job.total_rows })}
          </Button>
        </CardFooter>
        {runError && <p className="px-4 pb-4 text-sm text-destructive">{runError}</p>}
      </Card>
    </div>
  )
}

function PreviewTable({ rows, keys, label }: { rows: PreviewRow[]; keys: string[]; label: (key: string) => string }) {
  const { t } = useTranslation()
  return (
    <>
      {/* Phones: one card per row */}
      <ul className="divide-y md:hidden">
        {rows.map((row) => (
          <li key={row.line} className="grid gap-1.5 px-4 py-3 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground font-latin">#{row.line}</span>
              <Badge variant="outline" className={OUTCOME_STYLES[row.outcome]}>
                {t(`transfer.outcomes.${row.outcome}`)}
              </Badge>
            </div>
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5">
              {keys
                .filter((k) => row.values[k])
                .map((k) => (
                  <div key={k} className="contents">
                    <dt className="text-muted-foreground">{label(k)}</dt>
                    <dd className={cn('truncate', cellStyle(row, k))}>
                      <bdi>{row.values[k]}</bdi>
                    </dd>
                  </div>
                ))}
            </dl>
            {row.messages.length > 0 && <Messages row={row} />}
          </li>
        ))}
      </ul>
      {/* Wider screens: table */}
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-14 ps-4">{t('transfer.preview.line')}</TableHead>
              <TableHead>{t('transfer.preview.result')}</TableHead>
              {keys.map((k) => (
                <TableHead key={k}>{label(k)}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.line} className="align-top">
                <TableCell className="ps-4 text-muted-foreground font-latin">{row.line}</TableCell>
                <TableCell className="min-w-44 whitespace-normal">
                  <Badge variant="outline" className={OUTCOME_STYLES[row.outcome]}>
                    {t(`transfer.outcomes.${row.outcome}`)}
                  </Badge>
                  {row.messages.length > 0 && <Messages row={row} />}
                </TableCell>
                {keys.map((k) => (
                  <TableCell key={k} className={cn('max-w-48 truncate', cellStyle(row, k))} title={row.values[k]}>
                    <bdi>{row.values[k] || '—'}</bdi>
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  )
}

/** On updates, the cells that will be filled in stand out; the rest of the row is kept as it is. */
function cellStyle(row: PreviewRow, key: string) {
  if (row.outcome !== 'update') return undefined
  return row.changes.includes(key) ? 'font-medium text-primary' : 'text-muted-foreground'
}

function Messages({ row }: { row: PreviewRow }) {
  return (
    <ul className={cn('mt-1 grid gap-0.5 text-xs', row.outcome === 'fail' ? 'text-destructive' : 'text-muted-foreground')}>
      {row.messages.map((m) => (
        <li key={m}>
          {m}
        </li>
      ))}
    </ul>
  )
}
