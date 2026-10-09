import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import type { ContactStatus } from '@/lib/types'
import { cn } from '@/lib/utils'

// Theme tokens only, so the badges work in light and dark mode.
const STYLES: Record<ContactStatus, string> = {
  new: 'border-border bg-muted text-foreground',
  contacted: 'border-primary/30 bg-primary/10 text-primary',
  in_discussion: 'border-warning/40 bg-warning/15 text-foreground',
  won: 'border-success/40 bg-success/15 text-success',
  lost: 'border-destructive/30 bg-destructive/10 text-destructive',
}

export function StatusBadge({ status, className }: { status: ContactStatus; className?: string }) {
  const { t } = useTranslation()
  return (
    <Badge variant="outline" className={cn(STYLES[status], className)}>
      {t(`contacts.statuses.${status}`)}
    </Badge>
  )
}
