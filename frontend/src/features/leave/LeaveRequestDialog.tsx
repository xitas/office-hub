import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CalendarOff, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { FormDialog, FormField, SimpleSelect } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { api, apiError } from '@/lib/api'
import { todayInOffice } from '@/lib/bookings'
import { CALENDAR_KEY } from '@/lib/calendar'
import { useFormat } from '@/lib/format'
import { LEAVE_KEY, shortDays, typeName, useLeaveTypes, type HalfDay, type LeavePreview, type LeaveRequest } from '@/lib/leave'
import { useDebouncedValue } from '@/lib/useDebouncedValue'

/** Ask for leave: type, days (or half of one day), reason; shows the working days it takes and what's left. */
export function LeaveRequestDialog({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const fmt = useFormat()
  const queryClient = useQueryClient()
  const { data: types } = useLeaveTypes()
  const today = todayInOffice(fmt.settings.timezone)
  const [type, setType] = useState<number | null>(null)
  const [first, setFirst] = useState(today)
  const [last, setLast] = useState(today)
  const [halfDay, setHalfDay] = useState<HalfDay>('')
  const [reason, setReason] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const chosen = types?.find((x) => x.id === type) ?? types?.[0]
  const end = last < first ? first : last
  const single = first === end
  const half = single && chosen?.allow_half_days ? halfDay : ''
  const body = { leave_type: chosen?.id, start_date: first, end_date: end, half_day: half, reason }

  const key = useDebouncedValue(JSON.stringify({ t: chosen?.id, first, end, half }), 250)
  const preview = useQuery({
    queryKey: [...LEAVE_KEY, 'preview', key],
    queryFn: async () => (await api.post<LeavePreview>('/leave/requests/preview/', body)).data,
    enabled: !!chosen,
    retry: false,
  })

  const save = useMutation({
    mutationFn: async () => (await api.post<LeaveRequest>('/leave/requests/', body)).data,
    onSuccess: (req) => {
      void queryClient.invalidateQueries({ queryKey: LEAVE_KEY })
      void queryClient.invalidateQueries({ queryKey: CALENDAR_KEY })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      toast.success(req.status === 'approved' ? t('leave.approvedAtOnce') : t('leave.requested'))
      onClose()
    },
    onError: (e) => {
      const info = apiError(e)
      setErrors(info.fields)
      toast.error(Object.values(info.fields)[0] ?? info.message)
    },
  })

  const p = preview.data
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t('leave.request')}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => save.mutate()} disabled={!chosen || save.isPending || !!p?.problem || p?.days === '0.0'}>
            {save.isPending && <Loader2 className="size-4 animate-spin" />}
            {t('leave.send')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <FormField id="lv-type" label={t('leave.type')} error={errors.leave_type}>
          <SimpleSelect
            id="lv-type"
            value={chosen ? String(chosen.id) : ''}
            onChange={(v) => setType(Number(v))}
            options={(types ?? []).map((x) => ({ value: String(x.id), label: typeName(x, i18n.language) }))}
          />
        </FormField>
        <div className="grid grid-cols-2 gap-3">
          <FormField id="lv-first" label={t('leave.firstDay')} error={errors.start_date}>
            <Input id="lv-first" type="date" value={first} onChange={(e) => e.target.value && setFirst(e.target.value)} className="font-latin" />
          </FormField>
          <FormField id="lv-last" label={t('leave.lastDay')} error={errors.end_date}>
            <Input id="lv-last" type="date" value={end} min={first} onChange={(e) => e.target.value && setLast(e.target.value)} className="font-latin" />
          </FormField>
        </div>
        {single && chosen?.allow_half_days && (
          <FormField id="lv-half" label={t('leave.howLong')} error={errors.half_day}>
            <SimpleSelect
              id="lv-half"
              value={halfDay || 'whole'}
              onChange={(v) => setHalfDay(v === 'whole' ? '' : (v as HalfDay))}
              options={[
                { value: 'whole', label: t('leave.halfDays.whole') },
                { value: 'morning', label: t('leave.halfDays.morning') },
                { value: 'afternoon', label: t('leave.halfDays.afternoon') },
              ]}
            />
          </FormField>
        )}
        {p && (
          <div className="grid gap-1.5 rounded-md border p-3 text-sm" role="status">
            <p className="font-medium">
              {t('leave.takes', { days: shortDays(p.days) })}
              {p.remaining_after !== null && <span className="font-normal text-muted-foreground"> · {t('leave.leftAfter', { days: shortDays(p.remaining_after) })}</span>}
            </p>
            {p.skipped.length > 0 && (
              <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
                <CalendarOff className="mt-0.5 size-3.5 shrink-0" />
                {t('leave.notCounted', {
                  list: p.skipped.map((s) => `${fmt.date(`${s.date}T12:00:00`)} (${s.reason === 'holiday' ? s.title : t('leave.weekend')})`).join(', '),
                })}
              </p>
            )}
            {p.problem && (
              <p className="flex items-start gap-1.5 text-destructive">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                {p.problem}
              </p>
            )}
          </div>
        )}
        <FormField id="lv-reason" label={t('leave.reason')} hint={t('leave.reasonHint')}>
          <Textarea id="lv-reason" value={reason} dir="auto" maxLength={1000} onChange={(e) => setReason(e.target.value)} className="min-h-16" />
        </FormField>
      </div>
    </FormDialog>
  )
}
