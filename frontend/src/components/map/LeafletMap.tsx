import 'leaflet/dist/leaflet.css'
import L from 'leaflet'
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { DEFAULT_CENTER, DEFAULT_ZOOM, TILE_ATTRIBUTION, TILE_URL, type MapMarker, type PinKind } from '@/lib/map'

export interface LeafletMapProps {
  markers: MapMarker[]
  /** A draggable pin (the place being set), separate from the markers. */
  pin?: { lat: number; lng: number } | null
  onPinMove?: (lat: number, lng: number) => void
  /** Tapping the map (e.g. to drop the pin). */
  onMapClick?: (lat: number, lng: number) => void
  onMarkerClick?: (id: string) => void
  selected?: string | null
  /** Move the view here (e.g. a search result); changes of the object re-centre. */
  focus?: { lat: number; lng: number; zoom?: number } | null
  /** Fit the view around the markers when they change. */
  fit?: boolean
  className?: string
  label: string
}

const SHAPES: Record<PinKind, string> = {
  // Teardrop pins for places; dots for where people checked in and out.
  visit: 'pin', errand: 'pin', contact: 'pin', company: 'pin', vendor: 'pin', pin: 'pin', checkin: 'dot', checkout: 'dot',
}

function icon(kind: PinKind, tone: string | undefined, selected: boolean) {
  const cls = `crm-marker crm-marker-${kind}${tone ? ` crm-tone-${tone}` : ''}${selected ? ' crm-marker-selected' : ''}`
  if (SHAPES[kind] === 'dot') {
    return L.divIcon({ className: cls, html: '<span class="crm-dot"></span>', iconSize: [16, 16], iconAnchor: [8, 8] })
  }
  return L.divIcon({
    className: cls,
    html: '<svg viewBox="0 0 24 32" width="26" height="34" aria-hidden="true"><path class="crm-pin-body" d="M12 0C5.4 0 0 5.3 0 11.9 0 20.8 12 32 12 32s12-11.2 12-20.1C24 5.3 18.6 0 12 0z"/><circle cx="12" cy="12" r="4.5" class="crm-pin-hole"/></svg>',
    iconSize: [26, 34],
    iconAnchor: [13, 34],
    tooltipAnchor: [0, -30],
  })
}

/** Plain-text tooltip (names come from users: never HTML). */
function tooltip(text: string) {
  const el = document.createElement('span')
  el.dir = 'auto'
  el.textContent = text
  return el
}

/**
 * A Leaflet map with OpenStreetMap tiles. Loaded on demand (its own chunk). Tiles follow the usage policy: the
 * attribution is always shown, only what's on screen is loaded (no prefetching), and the Referer is sent
 * (strict-origin-when-cross-origin). Dark mode dims the tiles with a CSS filter; in Urdu the controls move to the
 * other side, while the map itself stays a map (north up, east right).
 */
export default function LeafletMap({ markers, pin, onPinMove, onMapClick, onMarkerClick, selected, focus, fit, className, label }: LeafletMapProps) {
  const { i18n } = useTranslation()
  const rtl = i18n.dir() === 'rtl'
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layer = useRef<L.LayerGroup | null>(null)
  const pinMarker = useRef<L.Marker | null>(null)
  const handlers = useRef({ onPinMove, onMapClick, onMarkerClick })
  useEffect(() => {
    handlers.current = { onPinMove, onMapClick, onMarkerClick }
  })

  // The map and its controls (again when the direction changes).
  useEffect(() => {
    if (!box.current) return
    const m = L.map(box.current, { zoomControl: false, attributionControl: false, center: DEFAULT_CENTER, zoom: DEFAULT_ZOOM })
    L.control.zoom({ position: rtl ? 'topright' : 'topleft' }).addTo(m)
    L.control.attribution({ position: rtl ? 'bottomleft' : 'bottomright', prefix: '<a href="https://leafletjs.com" target="_blank" rel="noopener">Leaflet</a>' })
      .addAttribution(TILE_ATTRIBUTION).addTo(m)
    L.tileLayer(TILE_URL, {
      maxZoom: 19,
      referrerPolicy: 'strict-origin-when-cross-origin',
      keepBuffer: 1, // no tiles beyond what's needed
      updateWhenZooming: false,
    }).addTo(m)
    layer.current = L.layerGroup().addTo(m)
    m.on('click', (e: L.LeafletMouseEvent) => handlers.current.onMapClick?.(e.latlng.lat, e.latlng.lng))
    map.current = m
    const resize = new ResizeObserver(() => m.invalidateSize())
    resize.observe(box.current)
    return () => {
      resize.disconnect()
      m.remove()
      map.current = null
      layer.current = null
      pinMarker.current = null
    }
  }, [rtl])

  // Markers.
  useEffect(() => {
    const m = map.current
    const group = layer.current
    if (!m || !group) return
    group.clearLayers()
    for (const mk of markers) {
      const marker = L.marker([mk.lat, mk.lng], { icon: icon(mk.kind, mk.tone, mk.id === selected), keyboard: true, title: mk.label, alt: mk.label })
      marker.bindTooltip(tooltip(mk.label), { direction: 'top' })
      marker.on('click', () => handlers.current.onMarkerClick?.(mk.id))
      group.addLayer(marker)
    }
    if (fit && markers.length) {
      const bounds = L.latLngBounds(markers.map((mk) => [mk.lat, mk.lng] as [number, number]))
      m.fitBounds(bounds.pad(0.2), { maxZoom: 15 })
    }
  }, [markers, selected, fit, rtl])

  // The draggable pin.
  useEffect(() => {
    const m = map.current
    if (!m) return
    if (!pin) {
      pinMarker.current?.remove()
      pinMarker.current = null
      return
    }
    if (!pinMarker.current) {
      pinMarker.current = L.marker([pin.lat, pin.lng], { icon: icon('pin', undefined, true), draggable: true, keyboard: true, autoPan: true }).addTo(m)
      pinMarker.current.on('dragend', () => {
        const at = pinMarker.current!.getLatLng()
        handlers.current.onPinMove?.(at.lat, at.lng)
      })
    } else {
      pinMarker.current.setLatLng([pin.lat, pin.lng])
    }
  }, [pin, rtl])

  useEffect(() => {
    if (focus && map.current) map.current.setView([focus.lat, focus.lng], focus.zoom ?? 16)
  }, [focus, rtl])

  return <div ref={box} dir="ltr" role="region" aria-label={label} className={className ?? 'h-80 w-full'} />
}
