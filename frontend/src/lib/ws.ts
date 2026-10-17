import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { toast } from 'sonner'
import { api } from './api'
import { useAuth } from './auth'
import { applyChatEvent, type ChatEvent } from './chat'
import type { AppNotification } from './types'

export const UNREAD_COUNT_KEY = ['notifications', 'unread-count'] as const

type ServerEvent =
  | { type: 'unread_count'; count: number }
  | { type: 'notification'; notification: AppNotification }
  | { type: 'pong' }
  | ChatEvent

// The open socket of this tab, and the conversation the tab shows (re-sent after a reconnect).
let current: WebSocket | null = null
let viewing: number | null = null

/** Send a message over this tab's WebSocket if it is open (typing, viewing). Dropped otherwise. */
export function sendRealtime(data: Record<string, unknown>) {
  if (current?.readyState === WebSocket.OPEN) current.send(JSON.stringify(data))
}

/** Tell the server which conversation this tab shows (no notifications for it). null when none or hidden. */
export function setViewing(conversation: number | null) {
  viewing = conversation
  sendRealtime({ type: 'chat.viewing', conversation: document.visibilityState === 'visible' ? viewing : null })
}

/**
 * Keeps one WebSocket open per signed-in tab and reconnects with backoff.
 * Each connection uses a fresh single-use ticket from /auth/ws-ticket/ (the api
 * client refreshes the access token for that call if needed). A ping every 30 s
 * keeps the user's online status alive.
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

    const onVisibility = () => setViewing(viewing)
    document.addEventListener('visibilitychange', onVisibility)

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
      current = socket

      socket.onopen = () => {
        attempts = 0
        pingTimer = window.setInterval(() => socket?.send(JSON.stringify({ type: 'ping' })), 30_000)
        setViewing(viewing)
        // Presence and messages may have changed while disconnected.
        void queryClient.invalidateQueries({ queryKey: ['chat'] })
      }
      socket.onmessage = (msg) => {
        const event = JSON.parse(msg.data) as ServerEvent
        if (event.type === 'unread_count') {
          queryClient.setQueryData(UNREAD_COUNT_KEY, { count: event.count })
        } else if (event.type === 'chat') {
          applyChatEvent(queryClient, event)
        } else if (event.type === 'notification') {
          queryClient.setQueryData<{ count: number }>(UNREAD_COUNT_KEY, (old) => ({ count: (old?.count ?? 0) + 1 }))
          void queryClient.invalidateQueries({ queryKey: ['notifications', 'list'] })
          void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
          if (event.notification.type === 'announcement') void queryClient.invalidateQueries({ queryKey: ['announcements'] })
          if (['booking', 'approval_request', 'approval_result'].includes(event.notification.type))
            void queryClient.invalidateQueries({ queryKey: ['bookings'] })
          if (['approval_request', 'approval_result'].includes(event.notification.type)) void queryClient.invalidateQueries({ queryKey: ['leave'] })
          if (['attendance', 'approval_result'].includes(event.notification.type)) void queryClient.invalidateQueries({ queryKey: ['attendance'] })
          if (event.notification.type === 'planning') void queryClient.invalidateQueries({ queryKey: ['planning'] })
          if (event.notification.type === 'vendor') void queryClient.invalidateQueries({ queryKey: ['vendors'] })
          if (['visit', 'approval_request', 'approval_result'].includes(event.notification.type)) void queryClient.invalidateQueries({ queryKey: ['visits'] })
          if (['low_stock', 'approval_request', 'approval_result'].includes(event.notification.type)) {
            void queryClient.invalidateQueries({ queryKey: ['supplies'] })
            void queryClient.invalidateQueries({ queryKey: ['expenses'] })
          }
          if (['meeting', 'office_event', 'approval_result'].includes(event.notification.type))
            void queryClient.invalidateQueries({ queryKey: ['calendar'] })
          toast(event.notification.title, { description: event.notification.body || undefined })
        }
      }
      socket.onclose = () => {
        window.clearInterval(pingTimer)
        if (current === socket) current = null
        if (stopped) return
        const delay = Math.min(30_000, 1000 * 2 ** attempts++)
        retryTimer = window.setTimeout(connect, delay)
      }
    }

    void connect()
    return () => {
      stopped = true
      document.removeEventListener('visibilitychange', onVisibility)
      window.clearTimeout(retryTimer)
      window.clearInterval(pingTimer)
      socket?.close()
    }
  }, [status, queryClient])
}
