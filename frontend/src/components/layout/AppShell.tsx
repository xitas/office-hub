import { Building } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Outlet } from 'react-router-dom'
import { useOrgSettings } from '@/lib/format'
import { useApplyUserPreferences } from '@/lib/preferences'
import { useRealtime } from '@/lib/ws'
import { BottomNav } from './BottomNav'
import { GlobalSearch } from './GlobalSearch'
import { NotificationBell } from './NotificationBell'
import { QuickAdd } from './QuickAdd'
import { Sidebar } from './Sidebar'
import { UserMenu } from './UserMenu'

export function AppShell() {
  const { t } = useTranslation()
  const { data: org } = useOrgSettings()
  useApplyUserPreferences()
  useRealtime()

  return (
    <div className="flex min-h-dvh">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-chrome/95 px-4 backdrop-blur md:px-6">
          {/* Mobile brand (sidebar is hidden on small screens) */}
          <div className="flex min-w-0 items-center gap-2 md:hidden">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Building className="size-4" />
            </div>
            <span className="truncate font-semibold">{org?.org_name || t('app.name')}</span>
          </div>
          <div className="flex flex-1 items-center justify-end gap-1 md:justify-between md:gap-3">
            <GlobalSearch />
            <div className="flex items-center gap-2">
              <div className="hidden md:block">
                <QuickAdd />
              </div>
              <NotificationBell />
              <UserMenu />
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 pt-6 pb-24 md:px-6 md:pb-10">
          <Outlet />
        </main>
      </div>
      <BottomNav />
    </div>
  )
}
