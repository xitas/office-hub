import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { Company, ContactStatus, Paginated } from './types'

export const CONTACT_STATUSES: ContactStatus[] = ['new', 'contacted', 'in_discussion', 'won', 'lost']

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
