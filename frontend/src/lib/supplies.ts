import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { Paginated } from './types'

export type SupplyCategory = 'stationery' | 'printing' | 'cleaning' | 'kitchen' | 'first_aid' | 'other'
export const SUPPLY_CATEGORIES: SupplyCategory[] = ['stationery', 'printing', 'cleaning', 'kitchen', 'first_aid', 'other']

export interface SupplyItem {
  id: number
  name: string
  name_ur: string
  category: SupplyCategory
  unit: string
  quantity: number
  reorder_level: number
  location: string
  notes: string
  is_active: boolean
  is_low: boolean
  /** Purchase requests waiting or approved (not received yet). */
  open_requests: number
  updated_at: string
}

export type StockKind = 'received' | 'used' | 'adjusted'

export interface StockMovement {
  id: number
  kind: StockKind
  change: number
  quantity_after: number
  note: string
  purchase_request: number | null
  by_name: string | null
  created_at: string
}

export type PurchaseStatus = 'pending' | 'approved' | 'rejected' | 'cancelled' | 'received'

export interface PurchaseRequest {
  id: number
  item: number | null
  item_name: string
  item_name_ur: string
  quantity: number
  unit: string
  reason: string
  estimated_cost: string | null
  requested_by: number
  requested_by_name: string
  department_name: string | null
  status: PurchaseStatus
  decided_by_name: string | null
  decided_at: string | null
  decision_note: string
  received_by_name: string | null
  received_at: string | null
  received_quantity: number | null
  can_decide: boolean
  can_cancel: boolean
  can_receive: boolean
  created_at: string
}

export const SUPPLIES_KEY = ['supplies'] as const

export function useSupplyItems(params: { q?: string; category?: string; low?: boolean; inactive?: boolean } = {}, enabled = true) {
  return useQuery({
    queryKey: [...SUPPLIES_KEY, 'items', params],
    queryFn: async () =>
      (await api.get<SupplyItem[]>('/inventory/items/', {
        params: { q: params.q || undefined, category: params.category || undefined, low: params.low ? 1 : undefined, inactive: params.inactive ? 1 : undefined },
      })).data,
    enabled,
    placeholderData: (previous) => previous,
  })
}

export function useStockHistory(itemId: number | null) {
  return useQuery({
    queryKey: [...SUPPLIES_KEY, 'history', itemId],
    queryFn: async () => (await api.get<StockMovement[]>(`/inventory/items/${itemId}/history/`)).data,
    enabled: itemId !== null,
  })
}

export type PurchaseScope = 'mine' | 'all' | 'approvals' | 'to_receive'

export function usePurchaseRequests(scope: PurchaseScope, enabled = true) {
  return useQuery({
    queryKey: [...SUPPLIES_KEY, 'requests', scope],
    queryFn: async () => (await api.get<Paginated<PurchaseRequest>>('/inventory/requests/', { params: { scope, page_size: 100 } })).data.results,
    enabled,
  })
}

/** The item's Urdu name in Urdu when it has one. */
export function itemName(x: { name?: string; name_ur?: string; item_name?: string; item_name_ur?: string }, language: string) {
  const ur = x.name_ur ?? x.item_name_ur
  return language === 'ur' && ur ? ur : (x.name ?? x.item_name ?? '')
}

export const PURCHASE_TONE: Record<PurchaseStatus, string> = {
  pending: 'border-amber-500/50 text-amber-700 dark:text-amber-300',
  approved: 'border-sky-500/50 text-sky-700 dark:text-sky-300',
  received: 'border-success/40 text-success',
  rejected: 'border-destructive/40 text-destructive',
  cancelled: 'text-muted-foreground',
}
