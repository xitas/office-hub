import { createContext, useContext } from 'react'
import type { ThemePref } from './types'

export const THEME_STORAGE_KEY = 'crm.theme'

export interface ThemeContextValue {
  /** The user's choice, including "system". */
  theme: ThemePref
  /** What is actually shown. */
  resolvedTheme: 'light' | 'dark'
  setTheme: (theme: ThemePref) => void
}

export const ThemeContext = createContext<ThemeContextValue | null>(null)

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>')
  return ctx
}
