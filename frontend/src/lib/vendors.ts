import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { Paginated } from './types'

export interface VendorCategory {
  id: number
  name: string
  name_ur: string
  position: number
  is_active: boolean
  vendor_count: number
}

export interface Vendor {
  id: number
  name: string
  categories: number[]
  contact_person: string
  phone: string
  whatsapp: string
  email: string
  website: string
  address: string
  city: string
  areas: string
  /** Where it is, for the map (optional). */
  latitude: string | null
  longitude: string | null
  payment_terms: string
  notes: string
  rating: number | null
  preferred: boolean
  is_active: boolean
  created_by_name: string | null
  created_at: string
  updated_at: string
  /** Managers and admins: mark preferred or inactive, delete unused vendors. */
  can_curate: boolean
}

export interface VendorActivity {
  supplies: { id: number; name: string; name_ur: string; quantity: number; unit: string; is_low: boolean }[]
  /** Null without the supplies permission; only the requests you may see. */
  purchases: { id: number; item_name: string; item_name_ur: string; quantity: number; unit: string; status: string; requested_by_name: string; created_at: string }[] | null
  /** Null without the expenses permission; only the claims you may see. */
  expenses: {
    currency: string
    year_count: number
    year_total: string
    recent: { id: number; title: string; amount: string; currency: string; spent_on: string; status: string; user_name: string }[]
  } | null
}

export const VENDORS_KEY = ['vendors'] as const

export interface VendorFilters {
  q?: string
  category?: string
  city?: string
  preferred?: boolean
  inactive?: boolean
  page?: number
}

export function useVendors(filters: VendorFilters) {
  return useQuery({
    queryKey: [...VENDORS_KEY, 'list', filters],
    queryFn: async () =>
      (await api.get<Paginated<Vendor>>('/vendors/', {
        params: {
          q: filters.q || undefined, category: filters.category || undefined, city: filters.city || undefined,
          preferred: filters.preferred ? 1 : undefined, inactive: filters.inactive ? 1 : undefined, page: filters.page,
        },
      })).data,
    placeholderData: (previous) => previous,
  })
}

export function useVendor(id: number) {
  return useQuery({
    queryKey: [...VENDORS_KEY, 'one', id],
    queryFn: async () => (await api.get<Vendor>(`/vendors/${id}/`)).data,
  })
}

export function useVendorActivity(id: number) {
  return useQuery({
    queryKey: [...VENDORS_KEY, 'activity', id],
    queryFn: async () => (await api.get<VendorActivity>(`/vendors/${id}/activity/`)).data,
  })
}

export function useVendorCategories() {
  return useQuery({
    queryKey: [...VENDORS_KEY, 'categories'],
    queryFn: async () => (await api.get<VendorCategory[]>('/vendors/categories/')).data,
    staleTime: 5 * 60_000,
  })
}

export function useVendorCities() {
  return useQuery({
    queryKey: [...VENDORS_KEY, 'cities'],
    queryFn: async () => (await api.get<string[]>('/vendors/cities/')).data,
    staleTime: 5 * 60_000,
  })
}

/** Active vendors for pickers (supplier, where to buy, paid to). */
export function useVendorOptions(enabled = true) {
  return useQuery({
    queryKey: [...VENDORS_KEY, 'options'],
    queryFn: async () => (await api.get<Paginated<Vendor>>('/vendors/', { params: { page_size: 200 } })).data.results,
    enabled,
    staleTime: 60_000,
  })
}

/** The category's Urdu name in Urdu when it has one. */
export function categoryName(c: { name: string; name_ur?: string }, language: string) {
  return language === 'ur' && c.name_ur ? c.name_ur : c.name
}
