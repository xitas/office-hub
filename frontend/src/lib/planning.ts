import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { addDays } from './bookings'

export interface WeeklyGoal {
  id: number
  week_start: string
  department: number | null
  department_name: string | null
  title: string
  description: string
  owner: number | null
  owner_name: string | null
  target: number
  unit: string
  current: number
  done: boolean
  position: number
  carried_from: number | null
  completed_at: string | null
  can_edit: boolean
  can_record: boolean
  updated_at: string
}

export interface WeekGoals {
  week_start: string
  week_end: string
  /** The week's last working day that isn't an office holiday (null if the whole week is off). */
  last_working_day: string | null
  can_plan: boolean
  goals: WeeklyGoal[]
}

export interface GoalUpdate {
  id: number
  before: number
  after: number
  note: string
  by_name: string | null
  created_at: string
}

export const PLANNING_KEY = ['planning'] as const

/** Loaded on its own (also for the dashboard card), so the dashboard's query count stays the same. */
export function useWeekGoals(week: string, department = '') {
  return useQuery({
    queryKey: [...PLANNING_KEY, 'week', week, department],
    queryFn: async () => (await api.get<WeekGoals>('/planning/goals/', { params: { week, department: department || undefined } })).data,
    placeholderData: (previous) => previous,
  })
}

export function useGoalHistory(id: number) {
  return useQuery({
    queryKey: [...PLANNING_KEY, 'history', id],
    queryFn: async () => (await api.get<GoalUpdate[]>(`/planning/goals/${id}/history/`)).data,
  })
}

export type GoalState = 'done' | 'onTrack' | 'behind' | 'notReached' | 'upcoming'

/**
 * Done, or how it's going against the share of the week's working days that have passed
 * (working days: 0 = Monday … 6 = Sunday, as on the Organization page).
 */
export function goalState(goal: WeeklyGoal, today: string, workingDays: number[]): GoalState {
  if (goal.done) return 'done'
  const days = Array.from({ length: 7 }, (_, i) => addDays(goal.week_start, i)).filter((d) =>
    workingDays.includes((new Date(`${d}T12:00:00Z`).getUTCDay() + 6) % 7),
  )
  if (!days.length || today < goal.week_start) return 'upcoming'
  if (today > addDays(goal.week_start, 6)) return 'notReached'
  const passed = days.filter((d) => d < today).length / days.length
  return goal.current / goal.target + 0.25 >= passed ? 'onTrack' : 'behind'
}

export const GOAL_TONE: Record<GoalState, string> = {
  done: 'border-success/40 text-success',
  onTrack: 'border-sky-500/50 text-sky-700 dark:text-sky-300',
  behind: 'border-amber-500/50 text-amber-700 dark:text-amber-300',
  notReached: 'border-destructive/40 text-destructive',
  upcoming: 'text-muted-foreground',
}

export const GOAL_BAR: Record<GoalState, string> = {
  done: 'bg-success',
  onTrack: 'bg-primary',
  behind: 'bg-amber-500',
  notReached: 'bg-destructive/70',
  upcoming: 'bg-primary',
}
