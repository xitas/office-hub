import { Building2, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { FormDialog, UserAvatar } from '@/components/common'
import { CreatedPanel } from '@/components/common/CreatedPanel'
import { RecordPicker, type Picked } from '@/components/common/RecordPicker'
import { Button } from '@/components/ui/button'
import { useAddEntry } from '@/lib/timeline'
import { EntryForm } from './EntryForm'


/** Quick add → Note: pick a contact or company (only ones the user can see), then write the note. */
export function QuickNoteDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [picked, setPicked] = useState<Picked | null>(null)
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
    <FormDialog open={open} onOpenChange={close} title={t('timeline.quickNote')} description={t('timeline.quickNoteHint')}>
      {saved ? (
        <CreatedPanel
          message={t('timeline.noteSaved', { name: saved.name })}
          onOpen={() => {
            close(false)
            navigate('contact' in saved.target ? `/contacts/${saved.target.contact}` : `/companies/${saved.target.company}`)
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
                <Building2 className="size-4 text-muted-foreground" />
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
            kinds={['note']}
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
