import type { Picked } from '@/components/common/RecordPicker'

const KEY = 'crm.pendingLog'
/** Coming back sooner than this is a mis-tap, not a call; later than MAX_AGE it's probably unrelated. */
const MIN_AWAY_MS = 3000
const MAX_AGE_MS = 2 * 60 * 60 * 1000

export interface PendingLog {
  kind: 'call' | 'whatsapp' | 'email'
  record: Picked
  at: number
  /** What was sent (from a template), to start the log entry with. */
  summary?: string
  subject?: string
}

/** Remember a click-to-call, WhatsApp or email, so the app can offer to log it on return. */
export function rememberContactAttempt(kind: PendingLog['kind'], record: Picked, sent?: { summary?: string; subject?: string }) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ kind, record, at: Date.now(), ...sent } satisfies PendingLog))
  } catch {
    /* private mode: no prompt, nothing else breaks */
  }
}

/** The remembered attempt, once the person has been away long enough (it is then forgotten). */
export function takePendingLog(): PendingLog | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const pending = JSON.parse(raw) as PendingLog
    const age = Date.now() - pending.at
    if (age < MIN_AWAY_MS) return null // still here: keep it for when they come back
    sessionStorage.removeItem(KEY)
    return age > MAX_AGE_MS ? null : pending
  } catch {
    return null
  }
}
