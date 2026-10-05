import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import i18n from '@/i18n'

/**
 * API client. The access token lives in memory only; the refresh token is an
 * httpOnly cookie scoped to /api/v1/auth/, so a page reload re-bootstraps via /auth/refresh/.
 */
// X-Requested-With marks requests as coming from our app (required for refresh-cookie endpoints: CSRF defence).
const APP_HEADERS = { 'X-Requested-With': 'XMLHttpRequest' }
export const api = axios.create({ baseURL: '/api/v1', withCredentials: true, headers: APP_HEADERS })

let accessToken: string | null = null
let refreshing: Promise<string | null> | null = null
let onSessionExpired: (() => void) | null = null

export const getAccessToken = () => accessToken
export const setAccessToken = (token: string | null) => {
  accessToken = token
}
export const setSessionExpiredHandler = (fn: () => void) => {
  onSessionExpired = fn
}

/** Single-flight refresh: concurrent 401s share one refresh request. */
export function refreshAccessToken(): Promise<string | null> {
  if (!refreshing) {
    refreshing = axios
      .post<{ access: string } | ''>('/api/v1/auth/refresh/', {}, { withCredentials: true, headers: APP_HEADERS })
      .then((res) => {
        // 204 = no session cookie (signed out); not an error.
        accessToken = res.status === 200 && res.data ? res.data.access : null
        return accessToken
      })
      .catch(() => {
        accessToken = null
        return null
      })
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
}

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`
  config.headers['Accept-Language'] = i18n.language
  return config
})

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined
    const isAuthCall = original?.url?.startsWith('/auth/login') || original?.url?.startsWith('/auth/refresh')
    if (error.response?.status === 401 && original && !original._retried && !isAuthCall) {
      original._retried = true
      const token = await refreshAccessToken()
      if (token) {
        original.headers.Authorization = `Bearer ${token}`
        return api(original)
      }
      onSessionExpired?.()
    }
    return Promise.reject(error)
  },
)

export interface ApiErrorInfo {
  message: string
  fields: Record<string, string>
}

/** Normalizes the backend's {detail, code, errors} error body. */
export function apiError(error: unknown, fallback = 'Something went wrong. Please try again.'): ApiErrorInfo {
  if (axios.isAxiosError(error)) {
    if (!error.response) return { message: 'Cannot reach the server. Check your connection.', fields: {} }
    const data = error.response.data as { detail?: string; errors?: Record<string, unknown> } | undefined
    const fields: Record<string, string> = {}
    for (const [key, value] of Object.entries(data?.errors ?? {})) {
      fields[key] = Array.isArray(value) ? String(value[0]) : String(value)
    }
    return { message: data?.detail || fallback, fields }
  }
  return { message: fallback, fields: {} }
}
