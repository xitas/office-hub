import { lazy, Suspense } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import type { LeafletMapProps } from './LeafletMap'

// Leaflet loads only when a map is shown (its own chunk).
const LeafletMap = lazy(() => import('./LeafletMap'))

export function MapView(props: LeafletMapProps) {
  return (
    <Suspense fallback={<Skeleton className={props.className ?? 'h-80 w-full'} />}>
      <LeafletMap {...props} />
    </Suspense>
  )
}

export type { LeafletMapProps }
