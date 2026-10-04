import { Bell, Paintbrush, Shield, UserRound } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { PageHeader } from '@/components/common'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { AppearanceTab } from './AppearanceTab'
import { NotificationPrefsTab } from './NotificationPrefsTab'
import { ProfileTab } from './ProfileTab'
import { SecurityTab } from './SecurityTab'

const TABS = [
  { value: 'profile', label: 'settings.profile', icon: UserRound },
  { value: 'appearance', label: 'settings.appearance', icon: Paintbrush },
  { value: 'security', label: 'settings.security', icon: Shield },
  { value: 'notifications', label: 'settings.notifications', icon: Bell },
]

export function SettingsPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const tab = TABS.some((x) => x.value === params.get('tab')) ? params.get('tab')! : 'profile'

  return (
    <>
      <PageHeader title={t('settings.title')} subtitle={t('settings.subtitle')} />
      <Tabs value={tab} onValueChange={(v) => setParams({ tab: String(v) }, { replace: true })}>
        <TabsList className="grid h-auto! w-full grid-cols-4 sm:inline-flex sm:h-8! sm:w-fit">
          {TABS.map((x) => (
            <TabsTrigger
              key={x.value}
              value={x.value}
              className="h-auto min-w-0 flex-col gap-0.5 px-1 py-1.5 text-[11px] sm:flex-row sm:gap-1.5 sm:px-2 sm:py-1 sm:text-sm"
            >
              <x.icon className="size-4" />
              <span className="max-w-full truncate sm:max-w-none sm:overflow-visible">{t(x.label)}</span>
            </TabsTrigger>
          ))}
        </TabsList>
        <div className="mt-4 max-w-2xl">
          <TabsContent value="profile">
            <ProfileTab />
          </TabsContent>
          <TabsContent value="appearance">
            <AppearanceTab />
          </TabsContent>
          <TabsContent value="security">
            <SecurityTab />
          </TabsContent>
          <TabsContent value="notifications">
            <NotificationPrefsTab />
          </TabsContent>
        </div>
      </Tabs>
    </>
  )
}
