import { useQueryClient, type QueryKey } from '@tanstack/react-query'
import { MapPinned } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { PinPickerDialog } from './PinPickerDialog'

/** A contact's, company's or vendor's pin (where it is, for the map), with "Set on map" for those who may edit. */
export function PlaceLocation({ name, latitude, longitude, path, canEdit, refresh }: {
  name: string
  latitude: string | null | undefined
  longitude: string | null | undefined
  /** e.g. /companies/3/ (PATCHed with latitude and longitude) */
  path: string
  canEdit: boolean
  refresh: QueryKey[]
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [picking, setPicking] = useState(false)
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      {latitude ? <bdi dir="ltr" className="font-latin">{latitude}, {longitude}</bdi> : <span className="text-muted-foreground">{t('map.noPin')}</span>}
      {canEdit && (
        <Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => setPicking(true)}>
          <MapPinned className="size-3.5" />
          {t(latitude ? 'map.changePin' : 'map.setPin')}
        </Button>
      )}
      {picking && (
        <PinPickerDialog title={t('map.pinTitle', { name })} latitude={latitude ?? null} longitude={longitude ?? null} onClose={() => setPicking(false)}
          onSave={async (lat, lng) => {
            await api.patch(path, { latitude: lat, longitude: lng })
            for (const key of [...refresh, ['map']]) void queryClient.invalidateQueries({ queryKey: key })
            toast.success(t(lat ? 'map.pinSaved' : 'map.pinCleared'))
          }} />
      )}
    </span>
  )
}
