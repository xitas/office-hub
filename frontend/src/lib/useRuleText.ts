import { useTranslation } from 'react-i18next'
import { useFormat } from './format'
import { describeRule, type Task } from './tasks'

const RULE_LOCALES: Record<string, string> = { en: 'en-PK', ur: 'ur-PK' }

/** The rule in plain words ("Every Monday and Thursday"). */
export function useRuleText(task: Pick<Task, 'repeat'>) {
  const { t, i18n } = useTranslation()
  const fmt = useFormat()
  if (!task.repeat?.active) return null
  return describeRule(task.repeat, t, RULE_LOCALES[i18n.language] ?? 'en-PK', fmt.date)
}
