import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { FormDialog, FormField } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import type { Contact, ContactStatus } from '@/lib/types'

/** Moving to these asks for an optional short reason (kept in the status history). */
const ASK_REASON: ContactStatus[] = ['won', 'lost']
const MAX_REASON = 500

interface Target {
  id: number
  full_name: string
  status: ContactStatus
}

interface Options {
  /** Called right before the request (optimistic UI). */
  onStart?: (contactId: number, to: ContactStatus) => void
  onSuccess?: (contact: Contact) => void
  /** Called when the request fails (undo the optimistic change). */
  onError?: () => void
}

/**
 * Change a contact's lead status — used by the pipeline board and the contact page.
 * Same request as editing the contact, so permissions, audit log and status history apply.
 */
export function useStatusChange({ onStart, onSuccess, onError }: Options = {}) {
  const { t } = useTranslation()
  const [asking, setAsking] = useState<{ target: Target; to: ContactStatus } | null>(null)
  const [reason, setReason] = useState('')
  const [pending, setPending] = useState<number | null>(null)

  const submit = async (target: Target, to: ContactStatus, statusReason = '') => {
    setPending(target.id)
    onStart?.(target.id, to)
    try {
      const { data } = await api.patch<Contact>(`/contacts/${target.id}/`, { status: to, status_reason: statusReason })
      onSuccess?.(data)
      toast.success(t('pipeline.moved', { name: target.full_name, status: t(`contacts.statuses.${to}`) }))
    } catch (err) {
      onError?.()
      toast.error(apiError(err).message)
    } finally {
      setPending(null)
    }
  }

  /** Start a move; asks for a reason first when moving to Won/Lost. */
  const requestChange = (target: Target, to: ContactStatus) => {
    if (to === target.status) return
    if (ASK_REASON.includes(to)) {
      setReason('')
      setAsking({ target, to })
    } else {
      void submit(target, to)
    }
  }

  const finish = (withReason: boolean) => (e?: FormEvent) => {
    e?.preventDefault()
    if (!asking) return
    const { target, to } = asking
    setAsking(null)
    void submit(target, to, withReason ? reason.trim() : '')
  }

  const dialog = asking && (
    <FormDialog
      open
      onOpenChange={(open) => !open && setAsking(null)}
      title={t(`pipeline.reasonTitle.${asking.to}`, { name: asking.target.full_name })}
      description={t('pipeline.reasonHint')}
    >
      <form onSubmit={finish(true)} className="grid gap-4">
        <FormField id="status-reason" label={t('pipeline.reason')}>
          <Textarea
            id="status-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value.slice(0, MAX_REASON))}
            rows={3}
            autoFocus
            placeholder={t(`pipeline.reasonPlaceholder.${asking.to}`)}
          />
        </FormField>
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => setAsking(null)}>
            {t('common.cancel')}
          </Button>
          <Button type="button" variant="outline" onClick={() => finish(false)()}>
            {t('pipeline.skip')}
          </Button>
          <Button type="submit" disabled={!reason.trim()}>
            {t('common.save')}
          </Button>
        </div>
      </form>
    </FormDialog>
  )

  return { requestChange, dialog, pending }
}
