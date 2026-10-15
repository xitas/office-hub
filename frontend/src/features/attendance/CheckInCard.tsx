import { useMutation, useQueryClient } from '@tanstack/react-query'
import { LogIn, LogOut, UserCheck } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { SimpleSelect } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { api, apiError } from '@/lib/api'
import { ATTENDANCE_KEY, COUNTED, STATUS_STYLES, useAttendanceToday, type AttendanceMode } from '@/lib/attendance'
import { useFormat } from '@/lib/format'
import { cn } from '@/lib/utils'

/** My attendance today, with check-in / check-out; managers and admins also see their team's counts. */
export function CheckInCard({ className, showTeam = true }: { className?: string; showTeam?: boolean }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const queryClient = useQueryClient()
  const { data, isLoading } = useAttendanceToday()
  const [mode, setMode] = useState<AttendanceMode>('office')
  const [note, setNote] = useState('')
  const act = useMutation({
    mutationFn: async (what: 'in' | 'out') =>
      what === 'in' ? api.post('/attendance/check-in/', { mode, note }) : api.post('/attendance/check-out/'),
    onSuccess: (_d, what) => {
      void queryClient.invalidateQueries({ queryKey: ATTENDANCE_KEY })
      setNote('')
      toast.success(what === 'in' ? t('attendance.checkedIn') : t('attendance.checkedOut'))
    },
    onError: (e) => toast.error(apiError(e).message),
  })
  const me = data?.me
  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center gap-2">
        <UserCheck className="size-4 text-muted-foreground" />
        <CardTitle className="flex-1 text-sm font-medium">{t('attendance.today')}</CardTitle>
        <Link to="/attendance" className="text-xs text-primary hover:underline">
          {t('attendance.open')}
        </Link>
      </CardHeader>
      <CardContent className="grid gap-3">
        {isLoading || !me ? (
          <Skeleton className="h-16" />
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge variant="outline" className={cn('font-normal', STATUS_STYLES[me.status])}>
                {t(`attendance.status.${me.status}`)}
              </Badge>
              {me.late && <Badge variant="outline" className="border-amber-500/50 font-normal text-amber-700 dark:text-amber-300">{t('attendance.late')}</Badge>}
              {me.check_in && <span className="text-muted-foreground">{t('attendance.inAt', { time: fmt.time(me.check_in) })}</span>}
              {me.check_out && <span className="text-muted-foreground">{t('attendance.outAt', { time: fmt.time(me.check_out) })}</span>}
              {me.holiday && <span className="text-muted-foreground"><bdi>{me.holiday}</bdi></span>}
            </div>
            {data.can_check_in && me.status !== 'leave' && (
              <div className="flex flex-wrap items-center gap-2">
                <div className="w-44">
                  <SimpleSelect
                    id="att-mode"
                    value={mode}
                    onChange={(v) => setMode(v as AttendanceMode)}
                    options={(['office', 'field', 'remote'] as const).map((m) => ({ value: m, label: t(`attendance.modes.${m}`) }))}
                  />
                </div>
                {mode !== 'office' && (
                  <Input value={note} dir="auto" maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder={t('attendance.notePlaceholder')} aria-label={t('attendance.note')} className="min-w-40 flex-1" />
                )}
                <Button onClick={() => act.mutate('in')} disabled={act.isPending}>
                  <LogIn className="size-4 rtl:rotate-180" />
                  {t('attendance.checkIn')}
                </Button>
              </div>
            )}
            {data.can_check_out && (
              <div>
                <Button variant="outline" onClick={() => act.mutate('out')} disabled={act.isPending}>
                  <LogOut className="size-4 rtl:rotate-180" />
                  {t('attendance.checkOut')}
                </Button>
              </div>
            )}
            {showTeam && data.team && (
              <div className="flex flex-wrap gap-1.5 border-t pt-3" aria-label={t('attendance.teamToday')}>
                {COUNTED.filter((k) => data.team![k] > 0).map((k) => (
                  <Badge key={k} variant="outline" className={cn('gap-1 font-normal', k === 'late' ? 'border-amber-500/50 text-amber-700 dark:text-amber-300' : STATUS_STYLES[k])}>
                    <span className="font-latin">{fmt.number(data.team![k])}</span>
                    {t(k === 'late' ? 'attendance.late' : `attendance.status.${k}`)}
                  </Badge>
                ))}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
