import { Card, CardContent } from '@/components/ui/card'
import { pct } from '@/lib/reports'
import { cn } from '@/lib/utils'

/** A single value from 0 to 100%: one hue, the number beside it in ordinary text colour. */
export function RateBar({ value, label }: { value: number | null; label: string }) {
  return (
    <span className="flex min-w-28 items-center gap-2">
      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100}
        aria-valuenow={value === null ? undefined : Math.round(value * 100)}>
        {value !== null && <span className="block h-full rounded-full bg-primary" style={{ width: `${Math.round(value * 100)}%` }} />}
      </span>
      <span className="w-10 text-end font-latin tabular-nums">{pct(value)}</span>
    </span>
  )
}

/** A headline number with its label (no chart). */
export function Tile({ label, value, hint, tone }: { label: string; value: string | number; hint?: string; tone?: 'bad' }) {
  return (
    <Card className="gap-1 py-4">
      <CardContent className="grid gap-0.5 px-4">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className={cn('font-latin text-2xl font-semibold tabular-nums', tone === 'bad' && 'text-destructive')}>{value}</span>
        {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
      </CardContent>
    </Card>
  )
}
