import { CheckCircle2, ExternalLink, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'

/** Shown in a quick-add dialog after saving: open the new record, or add another one. */
export function CreatedPanel({ message, onOpen, onAnother, onClose }: { message: string; onOpen: () => void; onAnother: () => void; onClose: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col items-center gap-4 py-4 text-center" role="status">
      <span className="rounded-full bg-success/15 p-3 text-success">
        <CheckCircle2 className="size-6" />
      </span>
      <p className="font-medium">
        <bdi>{message}</bdi>
      </p>
      <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
        <Button onClick={onOpen} autoFocus>
          <ExternalLink className="size-4" />
          {t('quickAdd.open')}
        </Button>
        <Button variant="outline" onClick={onAnother}>
          <Plus className="size-4" />
          {t('quickAdd.another')}
        </Button>
        <Button variant="ghost" onClick={onClose}>
          {t('common.close')}
        </Button>
      </div>
    </div>
  )
}
