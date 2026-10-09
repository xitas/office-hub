import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { Company, ContactStatus, Paginated } from './types'

export const CONTACT_STATUSES: ContactStatus[] = ['new', 'contacted', 'in_discussion', 'won', 'lost']

/** "Any" value for list filters. */
export const ALL = 'all'
export const CONTACT_FILTER_KEYS = ['status', 'company', 'city', 'tag', 'assigned_to'] as const
export type ContactFilterKey = (typeof CONTACT_FILTER_KEYS)[number]
export type ContactFilters = Record<ContactFilterKey, string>
export const EMPTY_CONTACT_FILTERS: ContactFilters = { status: ALL, company: ALL, city: ALL, tag: ALL, assigned_to: ALL }

/** Query-string params for the active filters (also accepted by /contacts/pipeline/). */
export function filterParams(filters: ContactFilters, omit: ContactFilterKey[] = []) {
  return Object.fromEntries(CONTACT_FILTER_KEYS.filter((k) => filters[k] !== ALL && !omit.includes(k)).map((k) => [k, filters[k]]))
}

export function useContactFacets() {
  return useQuery({
    queryKey: ['contacts', 'facets'],
    queryFn: async () => (await api.get<{ cities: string[]; tags: string[] }>('/contacts/facets/')).data,
    staleTime: 60_000,
  })
}

/** Companies this user can see, for pickers and filters. */
export function useCompanyOptions() {
  return useQuery({
    queryKey: ['companies', 'options'],
    queryFn: async () =>
      (await api.get<Paginated<Company>>('/companies/', { params: { page_size: 200, ordering: 'name' } })).data.results,
    staleTime: 60_000,
  })
}
