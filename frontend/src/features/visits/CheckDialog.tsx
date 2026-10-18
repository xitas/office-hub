import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, LocateFixed, LocateOff, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { FormDialog } from '@/components/common'
import { Button } from '@/components/ui/button'
import { api, apiError } from '@/lib/api'
import { useFormat } from '@/lib/format'
import { VISITS_KEY, type CheckLocation, type CheckSpot, type Visit, type VisitCheck } from '@/lib/visits'

/**
 * Check in or out at a visit. The note on what's recorded comes first; the browser asks for the location only
 * if the person chooses to share it. Declining, or a device that can't tell, still checks in ("no location").
 */
export function CheckDialog({ visit, mode, onClose }: { visit: Visit; mode: 'in' | 'out'; onClose: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [locating, setLocating] = useState(false)
  const send = useMutation({
    mutationFn: async (body: { location: CheckLocation; latitude?: number; longitude?: number; accuracy?: number }) =>
      api.post(`/visits/${visit.id}/check-${mode}/`, body),
    onSuccess: (_d, body) => {
      for (const key of [VISITS_KEY, ['attendance'], ['dashboard']]) void queryClient.invalidateQueries({ queryKey: key })
      toast.success(t(mode === 'in' ? 'visits.checks.inToast' : 'visits.checks.outToast') + (body.location === 'recorded' ? '' : ` (${t('visits.checks.noLocation')})`))
      onClose()
    },
    onError: (e) => toast.error(Object.values(apiError(e).fields)[0] ?? apiError(e).message),
  })
  const withLocation = () => {
    if (!navigator.geolocation) return send.mutate({ location: 'unavailable' })
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false)
        send.mutate({ location: 'recorded', latitude: Number(pos.coords.latitude.toFixed(6)), longitude: Number(pos.coords.longitude.toFixed(6)), accuracy: pos.coords.accuracy })
      },
      (err) => {
        setLocating(false)
        // Refused in the browser: "not shared"; anything else (no signal, timeout): "unavailable". Either way, checked in.
        send.mutate({ location: err.code === err.PERMISSION_DENIED ? 'declined' : 'unavailable' })
      },
      { enableHighAccuracy: true, timeout: 15_000, maximumAge: 0 },
    )
  }
  const busy = locating || send.isPending
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && !busy && onClose()}
      title={t(mode === 'in' ? 'visits.checks.inTitle' : 'visits.checks.outTitle', { title: visit.title })}
      footer={
        <>
          <Button variant="outline" disabled={busy} onClick={() => send.mutate({ location: 'declined' })}>
            <LocateOff className="size-4" />
            {t(mode === 'in' ? 'visits.checks.inWithout' : 'visits.checks.outWithout')}
          </Button>
          <Button disabled={busy} onClick={withLocation}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <LocateFixed className="size-4" />}
            {t(mode === 'in' ? 'visits.checks.inWith' : 'visits.checks.outWith')}
          </Button>
        </>
      }
    >
      <div className="flex gap-3 rounded-lg border bg-muted/40 p-3 text-sm">
        <ShieldCheck className="mt-0.5 size-5 shrink-0 text-primary" />
        <div className="grid gap-1.5">
          <p className="font-medium">{t('visits.checks.privacyTitle')}</p>
          <p>{t('visits.checks.privacyWhat')}</p>
          <p>{t('visits.checks.privacyWho')}</p>
          <p className="text-muted-foreground">{t('visits.checks.privacyOptional')}</p>
        </div>
      </div>
    </FormDialog>
  )
}

/** "31.521200, 74.359000 (±18 m) · 90 m from the pin", or why there's no location. */
export function SpotText({ spot, location, removed }: { spot: CheckSpot | null; location: CheckLocation | ''; removed: boolean }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const metres = (m: number) => (m < 1000 ? t('visits.checks.metres', { n: fmt.number(m) }) : t('visits.checks.km', { n: fmt.number(Math.round(m / 100) / 10) }))
  if (!location) return null
  if (location !== 'recorded') return <span className="text-muted-foreground">{t(`visits.checks.location.${location}`)}</span>
  if (removed) return <span className="text-muted-foreground">{t('visits.checks.removed')}</span>
  if (!spot) return <span className="text-muted-foreground">{t('visits.checks.location.recorded')}</span>
  return (
    <span>
      <bdi dir="ltr" className="font-latin">{spot.latitude}, {spot.longitude}</bdi>
      {spot.accuracy !== null && <span className="text-muted-foreground"> ({t('visits.checks.within', { m: metres(spot.accuracy) })})</span>}
      {spot.distance_m !== null && <span className="text-muted-foreground"> · {t('visits.checks.fromPin', { d: metres(spot.distance_m) })}</span>}
    </span>
  )
}

/** Each person's check-in and check-out: times for everyone allowed to see the visit, places only for those allowed. */
export function CheckList({ checks }: { checks: VisitCheck[] }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  if (!checks.length) return <span className="text-muted-foreground">{t('visits.checks.none')}</span>
  return (
    <ul className="grid gap-2">
      {checks.map((c) => (
        <li key={c.user} className="grid gap-0.5">
          <span className="font-medium"><bdi>{c.user_name}</bdi></span>
          <span>
            {t('visits.checks.inAt', { time: fmt.time(c.checked_in_at) })}
            {c.location_visible && <> · <SpotText spot={c.in} location={c.in_location} removed={c.location_removed} /></>}
          </span>
          {c.checked_out_at && (
            <span>
              {t('visits.checks.outAt', { time: fmt.time(c.checked_out_at) })}
              {c.location_visible && <> · <SpotText spot={c.out} location={c.out_location} removed={c.location_removed} /></>}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}
