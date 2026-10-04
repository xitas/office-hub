import { Check, Languages, LogOut, Monitor, Moon, Settings, Sun } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { RoleBadge, UserAvatar } from '@/components/common'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAuth, useMe } from '@/lib/auth'
import { useSetPreference } from '@/lib/preferences'
import { useTheme } from '@/lib/theme'
import type { Language, ThemePref } from '@/lib/types'

const THEMES: { value: ThemePref; icon: typeof Sun; label: string }[] = [
  { value: 'light', icon: Sun, label: 'settings.themeLight' },
  { value: 'dark', icon: Moon, label: 'settings.themeDark' },
  { value: 'system', icon: Monitor, label: 'settings.themeSystem' },
]

export function UserMenu() {
  const { t, i18n } = useTranslation()
  const me = useMe()
  const { logout } = useAuth()
  const navigate = useNavigate()
  const { theme } = useTheme()
  const prefs = useSetPreference()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="ghost" size="icon" className="rounded-full" aria-label={me.full_name} />}>
        <UserAvatar name={me.full_name} src={me.avatar} className="size-8" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="flex items-center gap-3 py-2">
            <UserAvatar name={me.full_name} src={me.avatar} className="size-9" />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground">{me.full_name}</p>
              <p className="truncate text-xs font-normal font-latin">{me.email}</p>
            </div>
          </DropdownMenuLabel>
          <div className="px-2 pb-1.5">
            <RoleBadge role={me.role} />
          </div>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem onClick={() => navigate('/settings')}>
            <Settings className="size-4" />
            {t('nav.settings')}
          </DropdownMenuItem>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <Sun className="size-4" />
              {t('settings.theme')}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              {THEMES.map((th) => (
                <DropdownMenuItem key={th.value} onClick={() => void prefs.setTheme(th.value)}>
                  <th.icon className="size-4" />
                  <span className="flex-1">{t(th.label)}</span>
                  {theme === th.value && <Check className="size-4" />}
                </DropdownMenuItem>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <Languages className="size-4" />
              {t('settings.language')}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              {(['en', 'ur'] as Language[]).map((lang) => (
                <DropdownMenuItem key={lang} onClick={() => void prefs.setLanguage(lang)}>
                  <span className="flex-1">{t(`languages.${lang}`)}</span>
                  {i18n.language === lang && <Check className="size-4" />}
                </DropdownMenuItem>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onClick={() => void logout()}>
          <LogOut className="size-4" />
          {t('common.signOut')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
