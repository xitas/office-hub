import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { ErrandKind, ErrandStatus } from './errands'
import type { VisitCheck, VisitStatus } from './visits'

/** OpenStreetMap's standard tiles (tile usage policy: attribution on every map, no prefetching, Referer kept). */
export const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
export const TILE_ATTRIBUTION = '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
/** Where the map opens when there's nothing to show: central Lahore. */
export const DEFAULT_CENTER: [number, number] = [31.5204, 74.3587]
export const DEFAULT_ZOOM = 12

export type PinKind = 'visit' | 'errand' | 'checkin' | 'checkout' | 'contact' | 'company' | 'vendor' | 'pin'

export interface MapMarker {
  id: string
  kind: PinKind
  lat: number
  lng: number
  /** Shown on hover/tap (plain text). */
  label: string
  /** Visits and errands: by status. */
  tone?: VisitStatus | ErrandStatus
}

export interface MapRecord {
  id: number
  name: string
  city: string
  latitude: string
  longitude: string
}

export interface MapVisit {
  id: number
  title: string
  status: VisitStatus
  purpose: string
  start: string
  end: string
  assigned_to: number
  assigned_to_name: string
  place: string
  latitude: string | null
  longitude: string | null
  /** Where the pin comes from: the visit's own, or its contact's, company's or vendor's. */
  pin_source: 'visit' | 'record' | null
  /** Coordinates only for those allowed to see them (null otherwise, and after 90 days). */
  checks: VisitCheck[]
}

export interface MapErrand {
  id: number
  title: string
  kind: ErrandKind
  status: ErrandStatus
  due_at: string | null
  place: string
  assigned_to_name: string | null
  latitude: string | null
  longitude: string | null
  pin_source: 'errand' | 'record' | null
}

export interface MapData {
  from: string
  to: string
  search_enabled: boolean
  visits: MapVisit[]
  errands: MapErrand[]
  contacts: MapRecord[]
  companies: MapRecord[]
  vendors: MapRecord[]
}

export interface MapQuery {
  from: string
  to: string
  person?: string
  status?: string
}

export function useMapData(query: MapQuery) {
  return useQuery({
    queryKey: ['map', query],
    queryFn: async () => (await api.get<MapData>('/map/', { params: query })).data,
  })
}

export function useMapConfig() {
  return useQuery({
    queryKey: ['map', 'config'],
    queryFn: async () => (await api.get<{ search_enabled: boolean; can_view_map: boolean }>('/map/config/')).data,
    staleTime: 10 * 60_000,
  })
}

export interface Place {
  name: string
  latitude: number
  longitude: number
  kind: string
}

/** Address search (through our server; Nominatim, cached, one a second). Only centres the map. */
export async function searchPlaces(q: string) {
  return (await api.get<{ results: Place[]; cached: boolean }>('/map/search/', { params: { q } })).data.results
}

export const toNumber = (v: string | number | null | undefined) => (v === null || v === undefined || v === '' ? null : Number(v))
