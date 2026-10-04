import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { ErrorState } from '@/components/common'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { api, apiError } from '@/lib/api'
import type { NotificationPref } from '@/lib/types'

const KEY = ['notifications', 'preferences']

export function NotificationPrefsTab() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: KEY,
    queryFn: async () => (await api.get<NotificationPref[]>('/notifications/preferences/')).data,
  })

  const save = useMutation({
    mutationFn: async (pref: NotificationPref) =>
      (await api.put<NotificationPref[]>('/notifications/preferences/', [pref])).data,
    onMutate: async (pref) => {
      queryClient.setQueryData<NotificationPref[]>(KEY, (old) => old?.map((p) => (p.type === pref.type ? pref : p)))
    },
    onSuccess: (prefs) => queryClient.setQueryData(KEY, prefs),
    onError: (err) => {
      toast.error(apiError(err).message)
      void refetch()
    },
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('settings.notifications')}</CardTitle>
      </CardHeader>
      <CardContent>
        {isError ? (
          <ErrorState onRetry={() => void refetch()} />
        ) : isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-6" />
            ))}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="py-2 text-start font-medium">{t('settings.prefType')}</th>
                <th className="w-20 py-2 text-center font-medium">{t('settings.inApp')}</th>
                <th className="w-20 py-2 text-center font-medium">{t('settings.emailChannel')}</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data?.map((p) => (
                <tr key={p.type}>
                  <td className="py-2.5 pe-2">{t(`notificationTypes.${p.type}`, { defaultValue: p.label })}</td>
                  <td className="text-center">
                    <Switch
                      checked={p.in_app}
                      onCheckedChange={(v) => save.mutate({ ...p, in_app: v })}
                      aria-label={`${p.label}: ${t('settings.inApp')}`}
                    />
                  </td>
                  <td className="text-center">
                    <Switch
                      checked={p.email}
                      onCheckedChange={(v) => save.mutate({ ...p, email: v })}
                      aria-label={`${p.label}: ${t('settings.emailChannel')}`}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  )
}
