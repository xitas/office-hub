import { Building, Languages } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function AuthLayout({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  const { t, i18n } = useTranslation()
  const other = i18n.language === 'ur' ? 'en' : 'ur'

  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <div className="flex justify-end p-4">
        <Button variant="ghost" size="sm" onClick={() => void i18n.changeLanguage(other)}>
          <Languages className="size-4" />
          {t(`languages.${other}`)}
        </Button>
      </div>
      <div className="flex flex-1 items-start justify-center px-4 pb-16 sm:items-center">
        <div className="w-full max-w-sm">
          <div className="mb-6 flex items-center justify-center gap-2">
            <div className="flex size-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <Building className="size-5" />
            </div>
            <span className="text-xl font-semibold">{t('app.name')}</span>
          </div>
          <Card>
            <CardHeader>
              <CardTitle className="text-xl">{title}</CardTitle>
              {subtitle && <CardDescription>{subtitle}</CardDescription>}
            </CardHeader>
            <CardContent>{children}</CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
