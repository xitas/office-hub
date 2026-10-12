import { previewOf, type ChatMessage } from '@/lib/chat'

// Mixed English/Urdu text: each paragraph finds its own direction, but lines up with the page.
export const BIDI_TEXT = '[unicode-bidi:plaintext] ltr:text-left rtl:text-right'

/** One line for screen readers when a message arrives. */
export function announce(m: ChatMessage, t: (k: string, o?: Record<string, unknown>) => string) {
  return t('chat.announce', { name: m.author?.full_name ?? t('chat.someone'), text: previewOf(m) })
}
