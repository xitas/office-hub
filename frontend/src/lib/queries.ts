import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { Department, Paginated, User } from './types'

export function useDepartments() {
  return useQuery({
    queryKey: ['departments', 'all'],
    queryFn: async () => (await api.get<Paginated<Department>>('/departments/', { params: { page_size: 200 } })).data.results,
    staleTime: 5 * 60_000,
  })
}

/** Active users for pickers (e.g. department manager). */
export function useUserOptions(role?: string) {
  return useQuery({
    queryKey: ['users', 'options', role ?? 'any'],
    queryFn: async () =>
      (await api.get<Paginated<User>>('/users/', { params: { page_size: 200, is_active: true, role } })).data.results,
    staleTime: 5 * 60_000,
  })
}

/** wa.me needs international digits only; local Pakistani 03xx numbers become 923xx. */
export function whatsappNumber(phone: string) {
  let digits = phone.replace(/\D/g, '')
  if (digits.startsWith('00')) digits = digits.slice(2)
  else if (digits.startsWith('0')) digits = `92${digits.slice(1)}`
  return digits
}
