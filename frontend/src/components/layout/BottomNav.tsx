import { LogOut, Menu } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router-dom'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useAuth, useMe } from '@/lib/auth'
import { visibleNavItems } from '@/lib/modules'
import { cn } from '@/lib/utils'
import { useUnreadCount } from './NotificationBell'

const MAX_PRIMARY = 4

/** Mobile navigation: four primary destinations plus a "More" sheet with everything else. */
export function BottomNav() {
  const { t } = useTranslation()
  const me = useMe()
  const { logout } = useAuth()
  const [moreOpen, setMoreOpen] = useState(false)
  const unread = useUnreadCount()

  const items = visibleNavItems(me.permissions)
  const primary = items.filter((i) => i.mobilePrimary).slice(0, MAX_PRIMARY)
  const rest = items.filter((i) => !primary.includes(i))

  const tabClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'relative flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px] text-muted-foreground',
      isActive && 'text-primary',
    )

  return (
    <>
      <nav className="pb-safe fixed inset-x-0 bottom-0 z-40 border-t bg-chrome/95 backdrop-blur md:hidden">
        <div className="flex h-16">
          {primary.map((item) => (
            <NavLink key={item.key} to={item.path} end={item.path === '/'} className={tabClass}>
              <span className="relative">
                <item.icon className="size-5" />
                {item.key === 'notifications' && unread > 0 && (
                  <span className="absolute -end-2 -top-1.5 min-w-4 rounded-full bg-destructive px-1 text-center text-[10px] leading-4 text-white font-latin">
                    {unread > 99 ? '99+' : unread}
                  </span>
                )}
              </span>
              <span className="truncate">{t(item.label)}</span>
            </NavLink>
          ))}
          <button
            type="button"
            className="flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px] text-muted-foreground"
            onClick={() => setMoreOpen(true)}
          >
            <Menu className="size-5" />
            <span>{t('nav.more')}</span>
          </button>
        </div>
      </nav>

      <Sheet open={moreOpen} onOpenChange={setMoreOpen}>
        <SheetContent side="bottom" className="pb-safe max-h-[80dvh] rounded-t-2xl">
          <SheetHeader>
            <SheetTitle>{t('nav.more')}</SheetTitle>
          </SheetHeader>
          <ul className="grid grid-cols-3 gap-2 px-4 pb-4">
            {rest.map((item) => (
              <li key={item.key}>
                <NavLink
                  to={item.path}
                  onClick={() => setMoreOpen(false)}
                  className={({ isActive }) =>
                    cn(
                      'flex flex-col items-center gap-1.5 rounded-xl border p-3 text-center text-xs',
                      isActive && 'border-primary text-primary',
                    )
                  }
                >
                  <item.icon className="size-5" />
                  <span className="line-clamp-2">{t(item.label)}</span>
                </NavLink>
              </li>
            ))}
            <li>
              <button
                type="button"
                onClick={() => void logout()}
                className="flex w-full flex-col items-center gap-1.5 rounded-xl border p-3 text-xs text-destructive"
              >
                <LogOut className="size-5" />
                {t('common.signOut')}
              </button>
            </li>
          </ul>
        </SheetContent>
      </Sheet>
    </>
  )
}
