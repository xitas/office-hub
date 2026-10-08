import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { useMe } from './auth'
import { useUserOptions } from './queries'
import type { Company } from './types'

/** Same keys as Company.Industry on the backend; labels live in i18n under companies.industries. */
export const INDUSTRIES = [
  'retail',
  'manufacturing',
  'services',
  'construction',
  'healthcare',
  'education',
  'technology',
  'finance',
  'real_estate',
  'logistics',
  'hospitality',
  'government',
  'other',
] as const

export type CompanyInput = Pick<
  Company,
  'name' | 'industry' | 'phone' | 'email' | 'website' | 'address' | 'city' | 'notes' | 'assigned_to'
>

export const EMPTY_COMPANY: CompanyInput = {
  name: '',
  industry: '',
  phone: '',
  email: '',
  website: '',
  address: '',
  city: '',
  notes: '',
  assigned_to: null,
}

export function useCompanyFacets() {
  return useQuery({
    queryKey: ['companies', 'facets'],
    queryFn: async () => (await api.get<{ cities: string[] }>('/companies/facets/')).data,
    staleTime: 60_000,
  })
}

/**
 * People this user may assign companies to (mirrors the API rules):
 * staff -> only themselves (null = no picker), managers -> their department, admins -> everyone.
 */
export function useAssignableUsers() {
  const me = useMe()
  const canAssignOthers = me.permissions.includes('contacts.assign_others')
  const { data } = useUserOptions()
  if (!canAssignOthers) return null
  const users = data ?? []
  return me.role === 'admin' ? users : users.filter((u) => u.id === me.id || (me.department && u.department === me.department))
}
