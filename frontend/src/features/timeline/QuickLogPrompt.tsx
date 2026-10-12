import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { takePendingLog, type PendingLog } from '@/lib/quickLog'
import { ENTRY_KINDS } from '@/lib/timeline'
import { QuickNoteDialog } from './QuickNoteDialog'

/** After calling or messaging a contact from the app, "Log this call/message" pre-filled with the contact. */
export function QuickLogPrompt() {
  const { t } = useTranslation()
  const [pending, setPending] = useState<PendingLog | null>(null)

  useEffect(() => {
    const check = () => {
      if (document.visibilityState !== 'visible') return
      const found = takePendingLog()
      if (found) setPending(found)
    }
    document.addEventListener('visibilitychange', check)
    window.addEventListener('focus', check)
    return () => {
      document.removeEventListener('visibilitychange', check)
      window.removeEventListener('focus', check)
    }
  }, [])

  if (!pending) return null
  return (
    <QuickNoteDialog
      open
      onOpenChange={(open) => !open && setPending(null)}
      kinds={ENTRY_KINDS}
      record={pending.record}
      initialKind={pending.kind}
      initialDirection="out"
      title={t(pending.kind === 'call' ? 'log.promptCall' : 'log.promptWhatsapp', { name: pending.record.name })}
      description={t('log.promptHint')}
    />
  )
}
