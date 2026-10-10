import { Building2, CalendarPlus, CheckSquare, NotebookPen, Plus, UserPlus, type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { QuickCreateDialog } from '@/features/quickadd/QuickCreateDialog'
import { QuickNoteDialog } from '@/features/timeline/QuickNoteDialog'
import { useMe } from '@/lib/auth'
import { NAV_ITEMS } from '@/lib/modules'

interface QuickAction {
  key: string
  label: string
  icon: LucideIcon
  /** Nav module that must be enabled for this action to work. */
  module: string
  permission: string
  /** Route that opens the "new" form for this record type (or a dialog opened in place). */
  path?: string
  dialog?: 'contact' | 'company' | 'note'
}

const ACTIONS: QuickAction[] = [
  { key: 'task', label: 'dashboard.task', icon: CheckSquare, module: 'tasks', permission: 'tasks.create', path: '/tasks?new=1' },
  { key: 'contact', label: 'dashboard.contact', icon: UserPlus, module: 'contacts', permission: 'contacts.create', dialog: 'contact' },
  { key: 'company', label: 'dashboard.company', icon: Building2, module: 'companies', permission: 'contacts.create', dialog: 'company' },
  { key: 'note', label: 'dashboard.note', icon: NotebookPen, module: 'contacts', permission: 'contacts.create', dialog: 'note' },
  { key: 'meeting', label: 'dashboard.meeting', icon: CalendarPlus, module: 'calendar', permission: 'calendar.create', path: '/calendar?new=1' },
]

export function QuickAdd({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation()
  const me = useMe()
  const navigate = useNavigate()
  const [dialog, setDialog] = useState<QuickAction['dialog'] | null>(null)
  const enabledModules = new Set(NAV_ITEMS.filter((n) => n.enabled).map((n) => n.key))

  const choose = (action: QuickAction) => {
    if (action.dialog) setDialog(action.dialog)
    else if (action.path) navigate(action.path)
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={compact ? <Button size="icon" aria-label={t('dashboard.quickAdd')} /> : <Button className="gap-1.5" />}
        >
          <Plus className="size-4" />
          {!compact && t('dashboard.quickAdd')}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuGroup>
            <DropdownMenuLabel>{t('dashboard.quickAdd')}</DropdownMenuLabel>
            {ACTIONS.map((action) => {
              const available = enabledModules.has(action.module) && me.permissions.includes(action.permission)
              return (
                <DropdownMenuItem key={action.key} disabled={!available} onClick={() => choose(action)}>
                  <action.icon className="size-4" />
                  <span className="flex-1">{t(action.label)}</span>
                  {!enabledModules.has(action.module) && (
                    <Badge variant="secondary" className="text-[10px]">
                      {t('common.comingSoon')}
                    </Badge>
                  )}
                </DropdownMenuItem>
              )
            })}
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      <QuickCreateDialog kind="contact" open={dialog === 'contact'} onOpenChange={(open) => setDialog(open ? 'contact' : null)} />
      <QuickCreateDialog kind="company" open={dialog === 'company'} onOpenChange={(open) => setDialog(open ? 'company' : null)} />
      <QuickNoteDialog open={dialog === 'note'} onOpenChange={(open) => setDialog(open ? 'note' : null)} />
    </>
  )
}
