import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'

/** "YYYY-MM" moved by some months. */
function shiftMonth(month: string, by: number) {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(Date.UTC(y, m - 1 + by, 1))
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`
}

/** Previous / next month buttons around the month's name ("October 2026"). */
export function MonthNav({ month, onMonth }: { month: string; onMonth: (m: string) => void }) {
  const { t, i18n } = useTranslation()
  const label = new Intl.DateTimeFormat(i18n.language === 'ur' ? 'ur-PK' : 'en-PK', { month: 'long', year: 'numeric', timeZone: 'UTC', numberingSystem: 'latn' })
    .format(new Date(`${month}-15T12:00:00Z`))
  return (
    <div className="flex items-center gap-1">
      <Button variant="outline" size="icon" aria-label={t('common.previousMonth')} onClick={() => onMonth(shiftMonth(month, -1))}>
        <ChevronLeft className="size-4 rtl:rotate-180" />
      </Button>
      <span className="min-w-36 text-center text-sm font-medium">{label}</span>
      <Button variant="outline" size="icon" aria-label={t('common.nextMonth')} onClick={() => onMonth(shiftMonth(month, 1))}>
        <ChevronRight className="size-4 rtl:rotate-180" />
      </Button>
    </div>
  )
}
