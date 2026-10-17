import { Building2, Store, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { FormDialog, UserAvatar } from '@/components/common'
import { CreatedPanel } from '@/components/common/CreatedPanel'
import { RecordPicker, type Picked } from '@/components/common/RecordPicker'
import { Button } from '@/components/ui/button'
import { targetPath, useAddEntry, type EntryKind } from '@/lib/timeline'
import { EntryForm } from './EntryForm'

/** Quick add → Note (and "Log" on the communication log, and "Log this call" after calling):
 *  pick a contact or company (only ones the user can see), or start with one, then log it. */
export function QuickNoteDialog({
  open,
  onOpenChange,
  kinds = ['note'],
  record,
  initialKind,
  initialDirection,
  initialSummary,
  initialSubject,
  title,
  description,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  kinds?: readonly EntryKind[]
  /** Start with this contact/company already chosen. */
  record?: Picked
  initialKind?: EntryKind
  initialDirection?: 'in' | 'out'
  /** Start the summary (and email subject) with this, e.g. the template text that was sent. */
  initialSummary?: string
  initialSubject?: string
  title?: string
  description?: string
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [picked, setPicked] = useState<Picked | null>(record ?? null)
  const [saved, setSaved] = useState<Picked | null>(null)
  const add = useAddEntry()

  const close = (next: boolean) => {
    onOpenChange(next)
    if (!next) {
      setPicked(null)
      setSaved(null)
    }
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={close}
      title={title ?? t('timeline.quickNote')}
      description={description ?? t('timeline.quickNoteHint')}
    >
      {saved ? (
        <CreatedPanel
          message={t(kinds.length === 1 && kinds[0] === 'note' ? 'timeline.noteSaved' : 'timeline.entrySaved', { name: saved.name })}
          onOpen={() => {
            close(false)
            navigate(targetPath(saved.target))
          }}
          onAnother={() => {
            setSaved(null)
            setPicked(null)
          }}
          onClose={() => close(false)}
        />
      ) : picked ? (
        <div className="grid gap-4">
          <div className="flex items-center gap-3 rounded-lg border bg-muted/30 p-2.5">
            {picked.type === 'contact' ? (
              <UserAvatar name={picked.name} className="size-8" />
            ) : (
              <span className="flex size-8 items-center justify-center rounded-full bg-muted">
                {picked.type === 'vendor' ? <Store className="size-4 text-muted-foreground" /> : <Building2 className="size-4 text-muted-foreground" />}
              </span>
            )}
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{picked.name}</p>
              {picked.hint && <p className="truncate text-xs text-muted-foreground">{picked.hint}</p>}
            </div>
            <Button variant="ghost" size="icon" className="size-8" aria-label={t('timeline.change')} onClick={() => setPicked(null)}>
              <X className="size-4" />
            </Button>
          </div>
          <EntryForm
            idPrefix="quick-note"
            kinds={kinds}
            initialKind={initialKind}
            initialDirection={initialDirection}
            initialSummary={initialSummary}
            initialSubject={initialSubject}
            contactId={'contact' in picked.target ? picked.target.contact : undefined}
            vendorId={'vendor' in picked.target ? picked.target.vendor : undefined}
            autoFocus
            onCancel={() => close(false)}
            onSubmit={async (input) => {
              await add.mutateAsync({ ...input, ...picked.target })
              setSaved(picked)
            }}
          />
        </div>
      ) : (
        <RecordPicker onPick={setPicked} />
      )}
    </FormDialog>
  )
}
