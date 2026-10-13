import { FileText, Search } from 'lucide-react'
import { useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { templateDir, useTemplates, type MessageTemplate, type TemplateChannel } from '@/lib/templates'
import { cn } from '@/lib/utils'

/** "Template" button: pick one of the templates for a channel (and "any channel"), most used first. */
export function TemplatePicker({
  channel,
  onPick,
  trigger,
  label,
  align = 'start',
}: {
  /** Templates for this channel (and "any channel" ones); 'any' lists every template. */
  channel: TemplateChannel
  onPick: (template: MessageTemplate) => void
  /** Custom trigger (gets the Popover trigger props). Default: a small outline button. */
  trigger?: ReactElement
  label?: string
  align?: 'start' | 'end'
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const { data, isLoading } = useTemplates(channel === 'any' ? {} : { channel }, open)
  const q = query.trim().toLowerCase()
  const shown = (data ?? []).filter((tpl) => !q || `${tpl.name} ${tpl.body}`.toLowerCase().includes(q))

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          trigger ?? (
            <Button type="button" variant="outline" size="sm">
              <FileText className="size-4" />
              {label ?? t('templates.useTemplate')}
            </Button>
          )
        }
      />
      <PopoverContent align={align} className="w-80 p-1.5">
        <div className="relative">
          <Search className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('templates.search')}
            aria-label={t('templates.search')}
            className="h-8 ps-8"
          />
        </div>
        <ul role="listbox" aria-label={t('templates.title')} className="mt-1 max-h-72 overflow-y-auto">
          {isLoading && <li className="px-2 py-3 text-sm text-muted-foreground">{t('common.loading')}</li>}
          {!isLoading && !shown.length && <li className="px-2 py-3 text-sm text-muted-foreground">{t('templates.noneForChannel')}</li>}
          {shown.map((tpl) => (
            <li key={tpl.id} role="option" aria-selected={false}>
              <button
                type="button"
                onClick={() => {
                  setOpen(false)
                  onPick(tpl)
                }}
                className="flex w-full flex-col gap-0.5 rounded-md px-2 py-1.5 text-start hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
              >
                <span className="flex items-center gap-2 text-sm font-medium">
                  <bdi className="min-w-0 flex-1 truncate">{tpl.name}</bdi>
                  <span className="shrink-0 rounded bg-muted px-1.5 text-[10px] font-normal text-muted-foreground uppercase font-latin">{tpl.language}</span>
                </span>
                <span dir={templateDir(tpl.language)} className={cn('line-clamp-2 text-xs text-muted-foreground', tpl.language === 'ur' ? 'text-right' : 'text-left')}>
                  {tpl.body}
                </span>
              </button>
            </li>
          ))}
        </ul>
        <div className="border-t px-2 pt-1.5 pb-0.5 text-end">
          <Link to="/templates" className="text-xs text-primary hover:underline" onClick={() => setOpen(false)}>
            {t('templates.manage')}
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  )
}
