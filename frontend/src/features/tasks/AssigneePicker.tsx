import { useTranslation } from 'react-i18next'
import { PeoplePicker } from '@/components/common/PeoplePicker'
import type { TaskAssignee } from '@/lib/tasks'
import { useTaskAssignees } from '@/lib/tasks'

/** Pick one or more people. Offers yourself and your department (admins: everyone); people
 *  already on the task stay listed even if they're outside that group. */
export function AssigneePicker({
  id,
  value,
  onChange,
  current = [],
  invalid,
}: {
  id: string
  value: number[]
  onChange: (ids: number[]) => void
  /** Assignees already saved on the task (shown even if this user couldn't add them). */
  current?: TaskAssignee[]
  invalid?: boolean
}) {
  const { t } = useTranslation()
  const options = useTaskAssignees()
  const people = [...options, ...current.filter((c) => !options.some((o) => o.id === c.id))]
  return <PeoplePicker id={id} value={value} onChange={onChange} people={people} placeholder={t('tasks.pickAssignees')} invalid={invalid} />
}
