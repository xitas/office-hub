import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export interface LeaveType {
  id: number
  name: string
  name_ur: string
  /** Days per year as text ("20.0"); null = no limit. */
  days_per_year: string | null
  paid: boolean
  allow_half_days: boolean
  is_active: boolean
  position: number
}

export type LeaveStatus = 'pending' | 'approved' | 'rejected' | 'cancelled'
export type HalfDay = '' | 'morning' | 'afternoon'

export interface LeaveRequest {
  id: number
  user: number
  user_name: string
  department_name: string | null
  leave_type: number
  type_name: string
  type_name_ur: string
  start_date: string
  end_date: string
  half_day: HalfDay
  days: string
  reason: string
  status: LeaveStatus
  decided_by_name: string | null
  decided_at: string | null
  decision_note: string
  can_cancel: boolean
  can_decide: boolean
  created_at: string
}

export interface LeaveBalance {
  id: number | null
  user: number
  user_name: string
  leave_type: number
  year: number
  limited: boolean
  allowance: string | null
  used: string
  pending: string
  remaining: string | null
  note: string
}

export interface TeamLeave {
  id: number
  user: number
  user_name: string
  type_name: string
  type_name_ur: string
  start_date: string
  end_date: string
  half_day: HalfDay
  days: string
}

export interface LeavePreview {
  days: string
  skipped: { date: string; reason: 'weekend' | 'holiday'; title: string }[]
  remaining: string | null
  remaining_after: string | null
  problem: string
}

export const LEAVE_KEY = ['leave'] as const

export function useLeaveTypes() {
  return useQuery({
    queryKey: [...LEAVE_KEY, 'types'],
    queryFn: async () => (await api.get<LeaveType[]>('/leave/types/')).data,
    staleTime: 60_000,
  })
}

export function useBalances(scope: 'mine' | 'team', year: number, enabled = true) {
  return useQuery({
    queryKey: [...LEAVE_KEY, 'balances', scope, year],
    queryFn: async () => (await api.get<LeaveBalance[]>('/leave/balances/', { params: { scope, year } })).data,
    enabled,
  })
}

export function useLeaveRequests(scope: 'mine' | 'team' | 'approvals', year: number, enabled = true) {
  return useQuery({
    queryKey: [...LEAVE_KEY, 'requests', scope, year],
    queryFn: async () => (await api.get<LeaveRequest[]>('/leave/requests/', { params: { scope, year } })).data,
    enabled,
  })
}

export function useTeamLeave(from: string, to: string) {
  return useQuery({
    queryKey: [...LEAVE_KEY, 'team', from, to],
    queryFn: async () => (await api.get<TeamLeave[]>('/leave/team/', { params: { from, to } })).data,
  })
}

/** The type's Urdu name in Urdu when it has one. */
export function typeName(t: { name?: string; type_name?: string; name_ur?: string; type_name_ur?: string }, language: string) {
  const ur = t.name_ur ?? t.type_name_ur
  return language === 'ur' && ur ? ur : (t.name ?? t.type_name ?? '')
}

/** "3", "2.5", "0.5": days without a trailing ".0". */
export function shortDays(value: string | null) {
  return value === null ? '' : String(Number(value))
}
