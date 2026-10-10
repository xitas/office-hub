import { api } from './api'

export type ImportKind = 'contacts' | 'companies'
export type ImportStatus = 'uploaded' | 'queued' | 'running' | 'done' | 'failed'
export type DuplicateMode = 'skip' | 'update' | 'create'

export interface ImportField {
  key: string
  label: string
  required: boolean
}

export interface ImportIssue {
  line: number
  outcome: 'skipped' | 'failed'
  reason: string
  values: string[]
}

export interface ImportOptions {
  duplicates: DuplicateMode
  create_companies: boolean
  assign_to: number | null
}

export interface ImportJob {
  id: number
  kind: ImportKind
  status: ImportStatus
  file_name: string
  headers: string[]
  sample: string[][]
  fields: ImportField[]
  mapping: Record<string, string>
  options: Partial<ImportOptions>
  background: boolean
  total_rows: number
  processed_rows: number
  created: number
  updated: number
  skipped: number
  failed: number
  issues: ImportIssue[]
  issue_count: number
  error: string
  created_at: string
  finished_at: string | null
}

export type ImportSummary = Pick<
  ImportJob,
  'id' | 'kind' | 'status' | 'file_name' | 'total_rows' | 'processed_rows' | 'created' | 'updated' | 'skipped' | 'failed' | 'created_at' | 'finished_at'
>

export interface PreviewRow {
  line: number
  values: Record<string, string>
  outcome: 'create' | 'update' | 'skip' | 'fail'
  /** Fields an update fills in (only empty ones; names and status never change). */
  changes: string[]
  messages: string[]
}

/** Badge colours for preview outcomes and result rows (theme tokens: light and dark). */
export const OUTCOME_STYLES: Record<string, string> = {
  create: 'border-success/40 bg-success/15 text-success',
  update: 'border-primary/30 bg-primary/10 text-primary',
  skip: 'border-border bg-muted text-muted-foreground',
  skipped: 'border-border bg-muted text-muted-foreground',
  fail: 'border-destructive/30 bg-destructive/10 text-destructive',
  failed: 'border-destructive/30 bg-destructive/10 text-destructive',
}

export const IMPORT_LIMITS = { megabytes: 5, rows: 5000 }

export const importPath = (kind: ImportKind, id?: number) => `/${kind}/import${id ? `/${id}` : ''}`

function filenameFrom(disposition: string | undefined, fallback: string) {
  const match = /filename="?([^";]+)"?/i.exec(disposition ?? '')
  return match?.[1] ?? fallback
}

/** Downloads a file from the API (with the user's token) and saves it under the server's file name. */
export async function downloadFile(url: string, params: Record<string, unknown> = {}, fallbackName = 'export.csv') {
  const res = await api.get<Blob>(url, { params, responseType: 'blob' })
  const href = URL.createObjectURL(res.data)
  const link = document.createElement('a')
  link.href = href
  link.download = filenameFrom(res.headers['content-disposition'] as string | undefined, fallbackName)
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}
