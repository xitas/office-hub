import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export type ExpenseCategory = 'travel' | 'fuel' | 'meals' | 'client' | 'supplies' | 'bills' | 'repairs' | 'other'
export const EXPENSE_CATEGORIES: ExpenseCategory[] = ['travel', 'fuel', 'meals', 'client', 'supplies', 'bills', 'repairs', 'other']

export type ExpenseStatus = 'pending' | 'approved' | 'rejected' | 'cancelled' | 'paid'

export interface Receipt {
  id: number
  original_name: string
  size: number
  content_type: string
  kind: 'image' | 'pdf' | 'office' | 'text' | 'zip'
  /** API paths (fetched with the user's token). */
  download_url: string
  thumbnail_url: string | null
}

export interface Expense {
  id: number
  user: number
  user_name: string
  department_name: string | null
  title: string
  category: ExpenseCategory
  amount: string
  currency: string
  spent_on: string
  description: string
  status: ExpenseStatus
  decided_by_name: string | null
  decided_at: string | null
  decision_note: string
  paid_by_name: string | null
  paid_at: string | null
  payment_note: string
  receipts: Receipt[]
  can_edit: boolean
  can_cancel: boolean
  can_decide: boolean
  can_pay: boolean
  created_at: string
}

export interface ExpenseSummary {
  month: string
  currency: string
  by_status: Record<ExpenseStatus, { count: number; amount: string }>
  /** Approved and paid amounts per category. */
  by_category: Partial<Record<ExpenseCategory, string>>
}

export type ExpenseScope = 'mine' | 'team' | 'approvals' | 'to_pay'

export const EXPENSES_KEY = ['expenses'] as const
export const MAX_RECEIPTS = 5

export function useExpenses(scope: ExpenseScope, month?: string, enabled = true) {
  return useQuery({
    queryKey: [...EXPENSES_KEY, 'list', scope, month ?? null],
    queryFn: async () => (await api.get<Expense[]>('/expenses/claims/', { params: { scope, month } })).data,
    enabled,
    placeholderData: (previous) => previous,
  })
}

export function useExpenseSummary(scope: 'mine' | 'team', month: string, enabled = true) {
  return useQuery({
    queryKey: [...EXPENSES_KEY, 'summary', scope, month],
    queryFn: async () => (await api.get<ExpenseSummary>('/expenses/claims/summary/', { params: { scope, month } })).data,
    enabled,
    placeholderData: (previous) => previous,
  })
}

export const EXPENSE_TONE: Record<ExpenseStatus, string> = {
  pending: 'border-amber-500/50 text-amber-700 dark:text-amber-300',
  approved: 'border-sky-500/50 text-sky-700 dark:text-sky-300',
  paid: 'border-success/40 text-success',
  rejected: 'border-destructive/40 text-destructive',
  cancelled: 'text-muted-foreground',
}

