import { Building, ChevronsLeft } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useMe } from '@/lib/auth'
import { useOrgSettings } from '@/lib/format'
import { visibleNavItems, type NavItem } from '@/lib/modules'
import { cn } from '@/lib/utils'

const STORAGE_KEY = 'crm.sidebar.collapsed'

function readCollapsed() {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

export function Sidebar() {
  const { t } = useTranslation()
  const me = useMe()
  const { data: org } = useOrgSettings()
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const items = visibleNavItems(me.permissions)
  const main = items.filter((i) => i.section === 'main')
  const admin = items.filter((i) => i.section === 'admin')

  const toggle = () => {
    setCollapsed((c) => {
      try {
        localStorage.setItem(STORAGE_KEY, c ? '0' : '1')
      } catch {
        /* ignore */
      }
      return !c
    })
  }

  return (
    <aside
      className={cn(
        'sticky top-0 hidden h-dvh shrink-0 flex-col border-e bg-sidebar text-sidebar-foreground transition-[width] duration-200 md:flex',
        collapsed ? 'w-16' : 'w-60',
      )}
    >
      <div className={cn('flex h-14 items-center gap-2 border-b px-4', collapsed && 'justify-center px-0')}>
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Building className="size-4" />
        </div>
        {!collapsed && <span className="truncate font-semibold">{org?.org_name || t('app.name')}</span>}
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto p-2">
        <NavSection items={main} collapsed={collapsed} />
        {admin.length > 0 && (
          <div>
            {!collapsed && (
              <p className="mb-1 px-3 text-xs font-medium tracking-wide text-muted-foreground uppercase">
                {t('nav.administration')}
              </p>
            )}
            <NavSection items={admin} collapsed={collapsed} />
          </div>
        )}
      </nav>

      <div className="border-t p-2">
        <Button
          variant="ghost"
          size="sm"
          className={cn('w-full justify-start gap-2 text-muted-foreground', collapsed && 'justify-center')}
          onClick={toggle}
          aria-label={collapsed ? t('nav.expand') : t('nav.collapse')}
        >
          <ChevronsLeft className={cn('size-4 transition-transform rtl:rotate-180', collapsed && 'rotate-180 rtl:rotate-0')} />
          {!collapsed && t('nav.collapse')}
        </Button>
      </div>
    </aside>
  )
}

function NavSection({ items, collapsed }: { items: NavItem[]; collapsed: boolean }) {
  const { t } = useTranslation()
  return (
    <ul className="space-y-0.5">
      {items.map((item) => {
        const link = (
          <NavLink
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              cn(
                'flex h-9 items-center gap-3 rounded-md px-3 text-sm transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                isActive && 'bg-sidebar-accent font-medium text-sidebar-primary',
                collapsed && 'justify-center px-0',
              )
            }
          >
            <item.icon className="size-4 shrink-0" />
            {!collapsed && <span className="truncate">{t(item.label)}</span>}
          </NavLink>
        )
        return (
          <li key={item.key}>
            {collapsed ? (
              <Tooltip>
                <TooltipTrigger render={<div />}>{link}</TooltipTrigger>
                <TooltipContent side="inline-end">{t(item.label)}</TooltipContent>
              </Tooltip>
            ) : (
              link
            )}
          </li>
        )
      })}
    </ul>
  )
}
