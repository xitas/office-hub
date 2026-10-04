import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, refreshAccessToken, setAccessToken, setSessionExpiredHandler } from './api'
import type { Me } from './types'

type Status = 'loading' | 'authenticated' | 'anonymous'

export type LoginResult = { otpRequired: false } | { otpRequired: true; otpToken: string }

interface AuthContextValue {
  status: Status
  user: Me | null
  login: (email: string, password: string) => Promise<LoginResult>
  verifyOtp: (otpToken: string, code: string) => Promise<void>
  logout: () => Promise<void>
  setUser: (user: Me) => void
  reloadUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

interface TokenResponse {
  access: string
  user: Me
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const [user, setUserState] = useState<Me | null>(null)
  const queryClient = useQueryClient()

  const signOutLocally = useCallback(() => {
    setAccessToken(null)
    setUserState(null)
    setStatus('anonymous')
    queryClient.clear()
  }, [queryClient])

  const acceptTokens = useCallback((data: TokenResponse) => {
    setAccessToken(data.access)
    setUserState(data.user)
    setStatus('authenticated')
  }, [])

  // Restore the session on page load using the httpOnly refresh cookie.
  useEffect(() => {
    let cancelled = false
    setSessionExpiredHandler(signOutLocally)
    refreshAccessToken()
      .then(async (token) => {
        if (!token) throw new Error('no session')
        const { data } = await api.get<Me>('/auth/me/')
        if (!cancelled) {
          setUserState(data)
          setStatus('authenticated')
        }
      })
      .catch(() => {
        if (!cancelled) setStatus('anonymous')
      })
    return () => {
      cancelled = true
    }
  }, [signOutLocally])

  const login = useCallback(
    async (email: string, password: string): Promise<LoginResult> => {
      const { data } = await api.post<TokenResponse | { otp_required: true; otp_token: string }>('/auth/login/', {
        email,
        password,
      })
      if ('otp_required' in data) return { otpRequired: true, otpToken: data.otp_token }
      acceptTokens(data)
      return { otpRequired: false }
    },
    [acceptTokens],
  )

  const verifyOtp = useCallback(
    async (otpToken: string, code: string) => {
      const { data } = await api.post<TokenResponse>('/auth/login/verify-otp/', { otp_token: otpToken, code })
      acceptTokens(data)
    },
    [acceptTokens],
  )

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout/')
    } finally {
      signOutLocally()
    }
  }, [signOutLocally])

  const reloadUser = useCallback(async () => {
    const { data } = await api.get<Me>('/auth/me/')
    setUserState(data)
  }, [])

  const value = useMemo(
    () => ({ status, user, login, verifyOtp, logout, setUser: setUserState, reloadUser }),
    [status, user, login, verifyOtp, logout, reloadUser],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

/** For components rendered only inside the authenticated shell. */
// eslint-disable-next-line react-refresh/only-export-components
export function useMe(): Me {
  const { user } = useAuth()
  if (!user) throw new Error('useMe used outside an authenticated route')
  return user
}
