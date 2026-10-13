import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, Copy, FileText, MoreHorizontal, Pencil, Plus, Search } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, FormField, PageHeader, SimpleSelect } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { api, apiError } from '@/lib/api'
import { useFormat } from '@/lib/format'
import {
  TEMPLATES_KEY,
  TEMPLATE_CATEGORIES,
  TEMPLATE_CHANNELS,
  TEMPLATE_LANGUAGES,
  templateDir,
  useTemplates,
  type MessageTemplate,
} from '@/lib/templates'
import { useDebouncedValue } from '@/lib/useDebouncedValue'
import { cn } from '@/lib/utils'
import { TemplateEditor } from './TemplateEditor'

const FILTERS = ['category', 'channel', 'language', 'owner', 'archived'] as const

/** Message templates: search and filters, create, edit, duplicate, archive. Most used first. */
export function TemplatesPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('q') ?? '')
  const q = useDebouncedValue(search.trim(), 250)
  const [editing, setEditing] = useState<MessageTemplate | 'new' | null>(null)
  const filters = Object.fromEntries([...FILTERS.map((k) => [k, params.get(k) ?? undefined]), ['q', q || undefined]])
  const { data, isLoading, isError, refetch } = useTemplates(filters)
  const set = (key: string, value: string) =>
    setParams((p) => {
      if (value) p.set(key, value)
      else p.delete(key)
      return p
    }, { replace: true })

  return (
    <>
      <PageHeader
        title={t('templates.title')}
        subtitle={t('templates.subtitle')}
        actions={
          <Button onClick={() => setEditing('new')}>
            <Plus className="size-4" />
            {t('templates.new')}
          </Button>
        }
      />
      <Card className="mb-4">
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          <label className="flex items-center gap-2 self-end rounded-md border bg-background px-2 sm:col-span-2">
            <Search className="size-4 text-muted-foreground" />
            <input
              type="search"
              value={search}
              dir="auto"
              onChange={(e) => {
                setSearch(e.target.value)
                set('q', e.target.value.trim())
              }}
              placeholder={t('templates.search')}
              aria-label={t('templates.search')}
              className="h-9 min-w-0 flex-1 bg-transparent text-sm outline-none"
            />
          </label>
          <FormField id="tf-category" label={t('templates.category')}>
            <SimpleSelect id="tf-category" value={params.get('category') ?? ''} onChange={(v) => set('category', v)}
              options={[{ value: '', label: t('templates.all') }, ...TEMPLATE_CATEGORIES.map((c) => ({ value: c, label: t(`templates.categories.${c}`) }))]} />
          </FormField>
          <FormField id="tf-channel" label={t('templates.channel')}>
            <SimpleSelect id="tf-channel" value={params.get('channel') ?? ''} onChange={(v) => set('channel', v)}
              options={[{ value: '', label: t('templates.all') }, ...TEMPLATE_CHANNELS.filter((c) => c !== 'any').map((c) => ({ value: c, label: t(`templates.channels.${c}`) }))]} />
          </FormField>
          <FormField id="tf-language" label={t('templates.language')}>
            <SimpleSelect id="tf-language" value={params.get('language') ?? ''} onChange={(v) => set('language', v)}
              options={[{ value: '', label: t('templates.all') }, ...TEMPLATE_LANGUAGES.map((l) => ({ value: l, label: t(`languages.${l}`) }))]} />
          </FormField>
          <FormField id="tf-owner" label={t('templates.owner')}>
            <SimpleSelect id="tf-owner" value={params.get('owner') ?? ''} onChange={(v) => set('owner', v)}
              options={['', 'mine', 'department', 'everyone'].map((o) => ({ value: o, label: t(`templates.owners.${o || 'all'}`) }))} />
          </FormField>
        </CardContent>
      </Card>
      <div className="mb-3 flex justify-end">
        <Button variant="ghost" size="sm" aria-pressed={params.get('archived') === 'true'} onClick={() => set('archived', params.get('archived') === 'true' ? '' : 'true')}>
          <Archive className="size-4" />
          {params.get('archived') === 'true' ? t('templates.hideArchived') : t('templates.showArchived')}
        </Button>
      </div>

      {isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isLoading ? (
        <div className="grid gap-3 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-40 rounded-xl" />
          ))}
        </div>
      ) : !data?.length ? (
        <EmptyState icon={FileText} title={t('templates.empty')} hint={t('templates.emptyHint')} className="py-16" />
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {data.map((tpl) => (
            <TemplateCard key={tpl.id} template={tpl} onEdit={() => setEditing(tpl)} />
          ))}
        </ul>
      )}
      {editing && <TemplateEditor template={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
    </>
  )
}

function TemplateCard({ template: tpl, onEdit }: { template: MessageTemplate; onEdit: () => void }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const queryClient = useQueryClient()
  const act = useMutation({
    mutationFn: async (what: 'archive' | 'unarchive' | 'duplicate') => (await api.post<MessageTemplate>(`/templates/${tpl.id}/${what}/`)).data,
    onSuccess: (_d, what) => {
      void queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY })
      toast.success(t(`templates.done.${what}`))
    },
    onError: (e) => toast.error(apiError(e).message),
  })
  const dir = templateDir(tpl.language)
  return (
    <li>
      <Card className={cn('h-full gap-3 py-4', tpl.archived && 'opacity-70')}>
        <CardContent className="grid h-full grid-rows-[auto_1fr_auto] gap-2">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-base font-semibold">
                <bdi>{tpl.name}</bdi>
              </h2>
              <div className="mt-1 flex flex-wrap gap-1.5">
                <Badge variant="secondary" className="font-normal">{t(`templates.categories.${tpl.category}`)}</Badge>
                <Badge variant="outline" className="font-normal">{t(`templates.channels.${tpl.channel}`)}</Badge>
                <Badge variant="outline" className="font-normal">{t(`languages.${tpl.language}`)}</Badge>
                {tpl.archived && <Badge variant="outline" className="font-normal">{t('templates.archived')}</Badge>}
              </div>
            </div>
            <DropdownMenu>
              <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" aria-label={t('templates.actions', { name: tpl.name })} />}>
                <MoreHorizontal className="size-4" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {tpl.can_edit && (
                  <DropdownMenuItem onClick={onEdit}>
                    <Pencil className="size-4" />
                    {t('common.edit')}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={() => act.mutate('duplicate')}>
                  <Copy className="size-4" />
                  {t('templates.duplicate')}
                </DropdownMenuItem>
                {tpl.can_edit &&
                  (tpl.archived ? (
                    <DropdownMenuItem onClick={() => act.mutate('unarchive')}>
                      <ArchiveRestore className="size-4" />
                      {t('templates.unarchive')}
                    </DropdownMenuItem>
                  ) : (
                    <DropdownMenuItem onClick={() => act.mutate('archive')}>
                      <Archive className="size-4" />
                      {t('templates.archive')}
                    </DropdownMenuItem>
                  ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          <div dir={dir} className={cn('rounded-md bg-muted/40 p-2.5 text-sm', dir === 'rtl' ? 'text-right' : 'text-left')}>
            {tpl.subject && <p className="mb-1 font-medium">{tpl.subject}</p>}
            <p className="line-clamp-4 whitespace-pre-wrap text-muted-foreground">{tpl.body}</p>
          </div>
          <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
            <span>{t(`templates.sharingOptions.${tpl.sharing}`)}{tpl.sharing === 'department' && tpl.department_name ? ` · ${tpl.department_name}` : ''}</span>
            {tpl.created_by_name && <span>· <bdi>{tpl.created_by_name}</bdi></span>}
            <span>· {t('templates.used', { count: tpl.usage_count })}</span>
            {tpl.last_used_at && <span>· {t('templates.lastUsed', { when: fmt.relative(tpl.last_used_at) })}</span>}
            {tpl.unknown_placeholders.length > 0 && (
              <span className="font-medium text-destructive">· {t('templates.hasUnknown')}</span>
            )}
          </p>
        </CardContent>
      </Card>
    </li>
  )
}
