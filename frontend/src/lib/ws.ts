import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { toast } from 'sonner'
import { api } from './api'
import { useAuth } from './auth'
import type { AppNotification } from './types'

export const UNREAD_COUNT_KEY = ['notifications', 'unread-count'] as const

type ServerEvent =
  | { type: 'unread_count'; count: number }
  | { type: 'notification'; notification: AppNotification }
  | { type: 'pong' }

/**
 * Keeps one WebSocket open per signed-in tab and reconnects with backoff.
 * Each connection uses a fresh single-use ticket from /auth/ws-ticket/ (the api
 * client refreshes the access token for that call if needed).
 */
export function useRealtime() {
  const { status } = useAuth()
  const queryClient = useQueryClient()

  useEffect(() => {
    if (status !== 'authenticated') return
    let socket: WebSocket | null = null
    let attempts = 0
    let stopped = false
    let retryTimer: number | undefined
    let pingTimer: number | undefined

    const connect = async () => {
      // A fresh single-use ticket per connection; the access token never goes in the URL.
      let ticket: string
      try {
        ticket = (await api.post<{ ticket: string }>('/auth/ws-ticket/')).data.ticket
      } catch {
        if (!stopped) retryTimer = window.setTimeout(connect, Math.min(30_000, 1000 * 2 ** attempts++))
        return
      }
      if (stopped) return
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      socket = new WebSocket(`${proto}://${window.location.host}/ws/notifications/?ticket=${encodeURIComponent(ticket)}`)

      socket.onopen = () => {
        attempts = 0
        pingTimer = window.setInterval(() => socket?.send(JSON.stringify({ type: 'ping' })), 30_000)
      }
      socket.onmessage = (msg) => {
        const event = JSON.parse(msg.data) as ServerEvent
        if (event.type === 'unread_count') {
          queryClient.setQueryData(UNREAD_COUNT_KEY, { count: event.count })
        } else if (event.type === 'notification') {
          queryClient.setQueryData<{ count: number }>(UNREAD_COUNT_KEY, (old) => ({ count: (old?.count ?? 0) + 1 }))
          void queryClient.invalidateQueries({ queryKey: ['notifications', 'list'] })
          void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
          toast(event.notification.title, { description: event.notification.body || undefined })
        }
      }
      socket.onclose = () => {
        window.clearInterval(pingTimer)
        if (stopped) return
        const delay = Math.min(30_000, 1000 * 2 ** attempts++)
        retryTimer = window.setTimeout(connect, delay)
      }
    }

    void connect()
    return () => {
      stopped = true
      window.clearTimeout(retryTimer)
      window.clearInterval(pingTimer)
      socket?.close()
    }
  }, [status, queryClient])
}
