import { useQueryClient } from '@tanstack/react-query'
import { CheckSquare, Plus } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { FormDialog } from '@/components/common'
import { Button } from '@/components/ui/button'
import { usePermission } from '@/lib/permissions'
import type { TimelineItem } from '@/lib/timeline'
import { TaskForm } from './TaskForm'

/** On a timeline entry with a follow-up date: "Create task" (due that day, linked to the record), or a link to the task made from it. */
export function FollowUpTaskButton({ item }: { item: TimelineItem & { follow_up_task?: number | null } }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const canCreate = usePermission('tasks.create')
  const [open, setOpen] = useState(false)
  if (!item.follow_up_on || item.entry_id === null) return null

  if (item.follow_up_task) {
    return (
      <Link to={`/tasks/${item.follow_up_task}`} className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
        <CheckSquare className="size-3.5" />
        {t('tasks.followUp.created')}
      </Link>
    )
  }
  if (!canCreate) return null

  const record = item.contact
    ? { type: 'contact' as const, id: item.contact.id, name: item.contact.name }
    : item.company
      ? { type: 'company' as const, id: item.company.id, name: item.company.name }
      : undefined
  const firstLine = (item.summary || '').split('\n')[0].trim()
  const title = t('tasks.followUp.title', { name: record?.name ?? '' }) + (firstLine ? `: ${firstLine.slice(0, 120)}` : '')

  return (
    <>
      <Button variant="link" size="sm" className="h-auto gap-1 p-0 text-xs" onClick={() => setOpen(true)}>
        <Plus className="size-3.5" />
        {t('tasks.followUp.create')}
      </Button>
      {open && (
        <FormDialog open onOpenChange={setOpen} title={t('tasks.followUp.dialogTitle')}>
          <TaskForm
            defaultDueDate={item.follow_up_on}
            defaults={{ title: title.slice(0, 200), description: item.summary, linked: record, followUpOf: item.entry_id }}
            onCancel={() => setOpen(false)}
            onSaved={() => {
              setOpen(false)
              toast.success(t('tasks.created'))
              void queryClient.invalidateQueries({ queryKey: ['timeline'] })
              void queryClient.invalidateQueries({ queryKey: ['tasks'] })
            }}
          />
        </FormDialog>
      )}
    </>
  )
}
