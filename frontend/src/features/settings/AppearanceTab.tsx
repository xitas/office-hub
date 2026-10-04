import { Monitor, Moon, Sun } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { useSetPreference } from '@/lib/preferences'
import type { Language, ThemePref } from '@/lib/types'
import { useTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'

const THEMES: { value: ThemePref; icon: typeof Sun; label: string }[] = [
  { value: 'light', icon: Sun, label: 'settings.themeLight' },
  { value: 'dark', icon: Moon, label: 'settings.themeDark' },
  { value: 'system', icon: Monitor, label: 'settings.themeSystem' },
]

function OptionTile({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'flex flex-col items-center gap-2 rounded-xl border p-4 text-sm transition-colors hover:bg-muted',
        active && 'border-primary bg-primary/5 text-primary',
      )}
    >
      {children}
    </button>
  )
}

export function AppearanceTab() {
  const { t, i18n } = useTranslation()
  const { theme } = useTheme()
  const prefs = useSetPreference()

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('settings.appearance')}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-6">
        <div className="grid gap-2">
          <Label>{t('settings.theme')}</Label>
          <div className="grid grid-cols-3 gap-2">
            {THEMES.map((th) => (
              <OptionTile key={th.value} active={theme === th.value} onClick={() => void prefs.setTheme(th.value)}>
                <th.icon className="size-5" />
                {t(th.label)}
              </OptionTile>
            ))}
          </div>
        </div>
        <div className="grid gap-2">
          <Label>{t('settings.language')}</Label>
          <div className="grid grid-cols-2 gap-2">
            {(['en', 'ur'] as Language[]).map((lang) => (
              <OptionTile key={lang} active={i18n.language === lang} onClick={() => void prefs.setLanguage(lang)}>
                <span className={cn('text-lg', lang === 'ur' ? '' : 'font-latin')}>{lang === 'ur' ? 'اردو' : 'English'}</span>
                <span className="text-xs text-muted-foreground">{t(`languages.${lang}`)}</span>
              </OptionTile>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">{t('settings.languageHint')}</p>
        </div>
      </CardContent>
    </Card>
  )
}
