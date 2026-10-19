import { useMutation } from '@tanstack/react-query'
import { Loader2, LocateFixed, MapPinOff, Search } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { FormDialog } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { apiError } from '@/lib/api'
import { searchPlaces, toNumber, useMapConfig, type Place } from '@/lib/map'
import { MapView } from '.'

type Pin = { lat: number; lng: number } | null

/**
 * Set where a place is: tap the map to drop the pin (drag it to adjust) or use my location (once, at the place).
 * Address search only moves the map; it never sets the pin by itself.
 */
export function PinPickerDialog({ title, latitude, longitude, onSave, onClose }: {
  title: string
  latitude: string | null
  longitude: string | null
  onSave: (latitude: string | null, longitude: string | null) => Promise<unknown> | void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { data: config } = useMapConfig()
  const start = toNumber(latitude) !== null ? { lat: toNumber(latitude)!, lng: toNumber(longitude)! } : null
  const [pin, setPin] = useState<Pin>(start)
  const [focus, setFocus] = useState<{ lat: number; lng: number; zoom?: number } | null>(start ? { ...start, zoom: 16 } : null)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Place[] | null>(null)
  const [locating, setLocating] = useState(false)
  const searching = useMutation({
    mutationFn: searchPlaces,
    onSuccess: (rows) => setResults(rows),
    onError: (e) => toast.error(apiError(e).message),
  })
  const saving = useMutation({
    mutationFn: async () => onSave(pin ? pin.lat.toFixed(6) : null, pin ? pin.lng.toFixed(6) : null),
    onSuccess: () => onClose(),
    onError: (e) => toast.error(Object.values(apiError(e).fields)[0] ?? apiError(e).message),
  })
  const here = () => {
    if (!navigator.geolocation) return toast.error(t('visits.noLocation'))
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false)
        const at = { lat: pos.coords.latitude, lng: pos.coords.longitude }
        setPin(at)
        setFocus({ ...at, zoom: 17 })
      },
      () => {
        setLocating(false)
        toast.error(t('visits.noLocation'))
      },
      { enableHighAccuracy: true, timeout: 15_000, maximumAge: 0 },
    )
  }
  const searchOn = config?.search_enabled ?? false
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && !saving.isPending && onClose()}
      title={title}
      className="sm:max-w-2xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving.isPending}>{t('common.cancel')}</Button>
          <Button onClick={() => saving.mutate()} disabled={saving.isPending}>
            {saving.isPending && <Loader2 className="size-4 animate-spin" />}
            {t('map.savePin')}
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (query.trim().length >= 3) searching.mutate(query.trim())
          }}
        >
          <Input value={query} dir="auto" onChange={(e) => setQuery(e.target.value)} disabled={!searchOn} placeholder={t('map.searchPlaceholder')} aria-label={t('map.search')} />
          <Button type="submit" variant="outline" disabled={!searchOn || query.trim().length < 3 || searching.isPending}>
            {searching.isPending ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />}
            {t('map.search')}
          </Button>
        </form>
        {config && !searchOn && <p className="text-xs text-muted-foreground">{t('map.searchOff')}</p>}
        {results && (
          results.length ? (
            <ul className="grid max-h-32 gap-1 overflow-y-auto text-sm">
              {results.map((r, i) => (
                <li key={i}>
                  <button type="button" className="w-full rounded-md px-2 py-1 text-start hover:bg-muted [unicode-bidi:plaintext]"
                    onClick={() => setFocus({ lat: r.latitude, lng: r.longitude, zoom: 16 })}>
                    {r.name}
                  </button>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-muted-foreground">{t('map.noResults')}</p>
        )}
        <MapView label={t('map.pickerLabel')} className="h-72 w-full overflow-hidden rounded-lg border sm:h-96" markers={[]} pin={pin} focus={focus}
          onMapClick={(lat, lng) => setPin({ lat, lng })} onPinMove={(lat, lng) => setPin({ lat, lng })} />
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="min-w-0 flex-1 text-muted-foreground">
            {pin ? <bdi dir="ltr" className="font-latin">{pin.lat.toFixed(6)}, {pin.lng.toFixed(6)}</bdi> : t('map.tapToPin')}
          </span>
          <Button type="button" variant="outline" size="sm" onClick={here} disabled={locating}>
            {locating ? <Loader2 className="size-4 animate-spin" /> : <LocateFixed className="size-4" />}
            {t('visits.useMyLocation')}
          </Button>
          {pin && (
            <Button type="button" variant="ghost" size="sm" onClick={() => setPin(null)}>
              <MapPinOff className="size-4" />
              {t('map.clearPin')}
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{t('map.pinNote')}</p>
      </div>
    </FormDialog>
  )
}
