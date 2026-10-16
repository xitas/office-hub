import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMe } from '@/lib/auth'
import { SLOT_MINUTES, minutesOf, placeBookings, timeOf, type Booking } from '@/lib/bookings'
import { useFormat } from '@/lib/format'
import { cn } from '@/lib/utils'

export interface TimelineRow {
  key: string
  label: string
  sublabel?: string
  resource: number
  date: string // office day "YYYY-MM-DD"
}

interface Selection {
  row: string
  anchor: number
  current: number
}

/**
 * Rows (resources, or days of one resource) across office hours. Drag across free 15-minute slots to
 * book that time; a click books an hour. Bookings are buttons that open their details.
 */
export function Timeline({
  rows,
  bookings,
  today,
  nowMinutes,
  onSelect,
  onOpen,
}: {
  rows: TimelineRow[]
  bookings: Booking[]
  today: string
  nowMinutes: number
  onSelect: (row: TimelineRow, start: number, end: number) => void
  onOpen: (booking: Booking) => void
}) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const me = useMe()
  const tz = fmt.settings.timezone
  const opens = minutesOf(fmt.settings.office_opens)
  const closes = minutesOf(fmt.settings.office_closes)
  const span = closes - opens
  const slots = Array.from({ length: span / SLOT_MINUTES }, (_, i) => opens + i * SLOT_MINUTES)
  const hours = slots.filter((m) => m % 60 === 0)
  const [selection, setSelectionState] = useState<Selection | null>(null)
  // The pointer-up listener reads the drag through a ref (it isn't re-created on every move).
  const selectionRef = useRef<Selection | null>(null)
  const setSelection = (sel: Selection | null) => {
    selectionRef.current = sel
    setSelectionState(sel)
  }

  const pct = (m: number) => `${((m - opens) / span) * 100}%`
  const pastSlot = (row: TimelineRow, m: number) => row.date < today || (row.date === today && m + SLOT_MINUTES <= nowMinutes)

  useEffect(() => {
    const finish = () => {
      const sel = selectionRef.current
      if (!sel) return
      selectionRef.current = null
      setSelectionState(null)
      const row = rows.find((r) => r.key === sel.row)
      if (!row) return
      const lo = Math.min(sel.anchor, sel.current)
      const hi = Math.max(sel.anchor, sel.current)
      const start = lo
      const end = lo === hi ? Math.min(lo + 60, closes) : hi + SLOT_MINUTES
      onSelect(row, start, end)
    }
    window.addEventListener('pointerup', finish)
    return () => window.removeEventListener('pointerup', finish)
  }, [rows, closes, onSelect])

  return (
    <div className="overflow-x-auto rounded-xl border bg-card">
      <div className="min-w-[720px] select-none">
        <div className="flex border-b text-[11px] text-muted-foreground">
          <div className="w-44 shrink-0 border-e px-3 py-2" />
          <div className="relative h-8 flex-1">
            {hours.map((m) => (
              <span key={m} className="absolute top-2 -translate-x-1/2 font-latin rtl:translate-x-1/2" style={{ insetInlineStart: pct(m) }}>
                {fmt.clock(timeOf(m))}
              </span>
            ))}
          </div>
        </div>
        {rows.map((row) => {
          const placed = placeBookings(bookings, row.resource, row.date, tz)
          const sel = selection?.row === row.key ? selection : null
          const selLo = sel ? Math.min(sel.anchor, sel.current) : 0
          const selHi = sel ? Math.max(sel.anchor, sel.current) + SLOT_MINUTES : 0
          return (
            <div key={row.key} className="flex border-b last:border-0">
              <div className="w-44 shrink-0 border-e px-3 py-2">
                <bdi className="block truncate text-sm font-medium">{row.label}</bdi>
                {row.sublabel && <span className="block truncate text-xs text-muted-foreground">{row.sublabel}</span>}
              </div>
              <div className="relative h-14 flex-1">
                {/* 15-minute slots: drag (or click) on free time to book. */}
                <div className="absolute inset-0 flex" aria-hidden="true">
                  {slots.map((m) => {
                    const past = pastSlot(row, m)
                    return (
                      <div
                        key={m}
                        onPointerDown={(e) => {
                          if (past || e.button !== 0) return
                          e.preventDefault()
                          setSelection({ row: row.key, anchor: m, current: m })
                        }}
                        onPointerEnter={() => {
                          if (selectionRef.current?.row === row.key && !past) setSelection({ ...selectionRef.current, current: m })
                        }}
                        className={cn(
                          'h-full flex-1',
                          m % 60 === 0 ? 'border-s border-border' : 'border-s border-border/30',
                          past ? 'bg-muted/60' : 'cursor-pointer hover:bg-primary/10',
                        )}
                      />
                    )
                  })}
                </div>
                {sel && (
                  <div
                    className="pointer-events-none absolute inset-y-1 rounded-md border-2 border-dashed border-primary bg-primary/15"
                    style={{ insetInlineStart: pct(selLo), width: `${((selHi - selLo) / span) * 100}%` }}
                  />
                )}
                {row.date === today && nowMinutes > opens && nowMinutes < closes && (
                  <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-destructive/70" style={{ insetInlineStart: pct(nowMinutes) }} />
                )}
                {placed.map(({ booking: b, start, end }) => {
                  const mine = b.booked_by === me.id || b.attendees.includes(me.id)
                  const s = Math.max(start, opens)
                  const e = Math.min(end, closes)
                  if (e <= s) return null
                  return (
                    <button
                      key={b.id}
                      type="button"
                      onClick={() => onOpen(b)}
                      onPointerDown={(ev) => ev.stopPropagation()}
                      title={`${b.title} · ${fmt.clock(timeOf(start))}–${fmt.clock(timeOf(end))} · ${b.booked_by_name}`}
                      aria-label={t('bookings.blockLabel', { title: b.title, start: fmt.clock(timeOf(start)), end: fmt.clock(timeOf(end)), name: b.booked_by_name })}
                      className={cn(
                        'absolute inset-y-1 overflow-hidden rounded-md border px-1.5 py-0.5 text-start text-[11px] leading-tight shadow-xs',
                        mine ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-secondary text-secondary-foreground',
                        b.status === 'pending' &&
                          'border-dashed border-amber-500 bg-amber-50 text-amber-900 dark:bg-amber-500/15 dark:text-amber-100 [background-image:repeating-linear-gradient(45deg,transparent,transparent_6px,rgb(245_158_11/0.12)_6px,rgb(245_158_11/0.12)_12px)]',
                      )}
                      style={{ insetInlineStart: pct(s), width: `${((e - s) / span) * 100}%` }}
                    >
                      <bdi className="block truncate font-medium">{b.title}</bdi>
                      <span className="block truncate opacity-80">
                        <span>{fmt.clock(timeOf(start))}–{fmt.clock(timeOf(end))}</span> · <bdi>{b.booked_by_name}</bdi>
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
