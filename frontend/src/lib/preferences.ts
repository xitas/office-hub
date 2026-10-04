import { useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from './api'
import { useAuth } from './auth'
import { useTheme } from './theme'
import type { Language, Me, ThemePref } from './types'

/** Applies the signed-in user's saved language and theme once their profile loads. */
export function useApplyUserPreferences() {
  const { user } = useAuth()
  const { i18n } = useTranslation()
  const { setTheme } = useTheme()

  useEffect(() => {
    if (!user) return
    if (user.language !== i18n.language) void i18n.changeLanguage(user.language)
    setTheme(user.theme)
    // Only re-apply when the saved values change, not on every user object refresh.
  }, [user?.language, user?.theme]) // eslint-disable-line react-hooks/exhaustive-deps
}

/** Change language/theme immediately and persist it to the profile (when signed in). */
export function useSetPreference() {
  const { user, setUser } = useAuth()
  const { i18n } = useTranslation()
  const { setTheme } = useTheme()

  const persist = useCallback(
    async (patch: Partial<Pick<Me, 'language' | 'theme'>>) => {
      if (!user) return
      const { data } = await api.patch<Me>('/auth/me/', patch)
      setUser(data)
    },
    [user, setUser],
  )

  const setLanguage = useCallback(
    (language: Language) => {
      void i18n.changeLanguage(language)
      return persist({ language })
    },
    [i18n, persist],
  )

  const setThemePref = useCallback(
    (theme: ThemePref) => {
      setTheme(theme)
      return persist({ theme })
    },
    [setTheme, persist],
  )

  return { setLanguage, setTheme: setThemePref }
}
