import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CheckCheck, Clock, Megaphone, Pencil, Pin, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState, ErrorState, UserAvatar } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { AttachmentChip } from '@/features/chat/MessageItem'
import { ANNOUNCEMENTS_KEY, textDir, useAnnouncement, useReceipts, type Announcement, type ReceiptPerson } from '@/lib/announcements'
import { api, apiError } from '@/lib/api'
import { useConfirm } from '@/lib/confirm'
import { useFormat } from '@/lib/format'
import { UNREAD_COUNT_KEY } from '@/lib/ws'
import { AnnouncementBody } from './AnnouncementBody'
import { AnnouncementEditor } from './AnnouncementEditor'

/** One announcement. Opening it records that you read it; the author and admins see who has and hasn't. */
export function AnnouncementPage() {
  const { t } = useTranslation()
  const fmt = useFormat()
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const confirm = useConfirm()
  const queryClient = useQueryClient()
  const { data: a, isLoading, isError, error, refetch } = useAnnouncement(id)
  const [editing, setEditing] = useState(false)

  const markRead = useMutation({
    mutationFn: async () => (await api.post(`/announcements/${id}/read/`)).data,
    onSuccess: () => {
      queryClient.setQueryData<Announcement>([...ANNOUNCEMENTS_KEY, 'detail', id], (old) => (old ? { ...old, is_read: true } : old))
      void queryClient.invalidateQueries({ queryKey: [...ANNOUNCEMENTS_KEY, 'list'] })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      void queryClient.invalidateQueries({ queryKey: UNREAD_COUNT_KEY })
      void queryClient.invalidateQueries({ queryKey: ['notifications', 'list'] })
    },
  })
  const unread = a && !a.is_read
  const { mutate: read } = markRead
  useEffect(() => {
    if (unread) read()
  }, [unread, read])

  const remove = useMutation({
    mutationFn: async () => api.delete(`/announcements/${id}/`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ANNOUNCEMENTS_KEY })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      toast.success(t('announcements.deleted'))
      navigate('/announcements')
    },
    onError: (e) => toast.error(apiError(e).message),
  })

  const back = (
    <Button variant="ghost" size="sm" className="-ms-2 mb-3" nativeButton={false} render={<Link to="/announcements" />}>
      <ArrowLeft className="size-4 rtl:rotate-180" />
      {t('announcements.back')}
    </Button>
  )

  if (isLoading) return <Skeleton className="h-96 max-w-3xl rounded-xl" />
  if (isError || !a) {
    const notFound = (error as { response?: { status?: number } } | null)?.response?.status === 404
    return (
      <>
        {back}
        {notFound ? <EmptyState icon={Megaphone} title={t('announcements.notFound')} className="py-16" /> : <ErrorState onRetry={() => void refetch()} />}
      </>
    )
  }

  return (
    <div className="max-w-3xl">
      {back}
      <Card>
        <CardContent className="grid gap-4">
          <div className="flex flex-wrap items-start gap-2">
            <h1 dir={textDir(a.title)} className="min-w-0 flex-1 text-xl font-semibold [overflow-wrap:anywhere]">
              {a.title}
            </h1>
            {a.pinned && !a.expired && (
              <Badge variant="secondary" className="gap-1 font-normal">
                <Pin className="size-3" />
                {t('announcements.pinnedBadge')}
              </Badge>
            )}
            {a.expired && <Badge variant="outline" className="font-normal">{t('announcements.archived')}</Badge>}
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-muted-foreground">
            {a.created_by_name && (
              <span className="flex items-center gap-2">
                <UserAvatar name={a.created_by_name} className="size-6" />
                <bdi className="font-medium text-foreground">{a.created_by_name}</bdi>
              </span>
            )}
            <bdi className="font-latin">{fmt.dateTime(a.published_at)}</bdi>
            <span>{a.audience === 'everyone' ? t('announcements.audiences.everyone') : t('announcements.forList', { names: a.department_names.join(', ') })}</span>
            {a.expires_on && (
              <span className="inline-flex items-center gap-1">
                <Clock className="size-3.5" />
                {t(a.expired ? 'announcements.expiredOn' : 'announcements.until', { date: fmt.date(`${a.expires_on}T12:00:00`) })}
              </span>
            )}
          </div>
          <AnnouncementBody body={a.body} className="text-base" />
          {a.attachments.length > 0 && (
            <div className="grid gap-2">
              <h2 className="text-sm font-medium">{t('announcements.files')}</h2>
              <div className="flex flex-wrap gap-2">
                {a.attachments.map((file) => (
                  <AttachmentChip key={file.id} attachment={file} />
                ))}
              </div>
            </div>
          )}
          {a.can_edit && (
            <div className="flex flex-wrap gap-2 border-t pt-4">
              <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                <Pencil className="size-4" />
                {t('common.edit')}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="text-destructive"
                disabled={remove.isPending}
                onClick={async () => {
                  const ok = await confirm({
                    title: t('announcements.deleteTitle'),
                    description: t('announcements.deleteText', { title: a.title }),
                    confirmLabel: t('common.delete'),
                    destructive: true,
                  })
                  if (ok) remove.mutate()
                }}
              >
                <Trash2 className="size-4" />
                {t('common.delete')}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
      {a.can_edit && <ReceiptsCard id={a.id} />}
      {editing && <AnnouncementEditor announcement={a} onClose={() => setEditing(false)} />}
    </div>
  )
}

function ReceiptsCard({ id }: { id: number }) {
  const { t } = useTranslation()
  const fmt = useFormat()
  const { data, isLoading } = useReceipts(id, true)
  const share = data && data.total ? Math.round((data.read_count / data.total) * 100) : 0
  return (
    <Card className="mt-4">
      <CardHeader className="flex flex-row items-center gap-2">
        <CheckCheck className="size-4 text-muted-foreground" />
        <CardTitle className="flex-1 text-sm font-medium">{t('announcements.receipts')}</CardTitle>
        {data && (
          <span className="text-sm font-medium">
            {t('announcements.readBy', { read: fmt.number(data.read_count), total: fmt.number(data.total) })}
          </span>
        )}
      </CardHeader>
      <CardContent className="grid gap-3">
        {isLoading || !data ? (
          <Skeleton className="h-24" />
        ) : (
          <>
            <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={share} aria-valuemin={0} aria-valuemax={100} aria-label={t('announcements.receipts')}>
              <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${share}%` }} />
            </div>
            <Tabs defaultValue={data.unread.length ? 'unread' : 'read'}>
              <TabsList>
                <TabsTrigger value="unread">
                  {t('announcements.notRead')} <span className="font-latin">({fmt.number(data.unread.length)})</span>
                </TabsTrigger>
                <TabsTrigger value="read">
                  {t('announcements.readTab')} <span className="font-latin">({fmt.number(data.read.length)})</span>
                </TabsTrigger>
              </TabsList>
              <TabsContent value="unread">
                <People people={data.unread} empty={t('announcements.everyoneRead')} />
              </TabsContent>
              <TabsContent value="read">
                <People people={data.read} empty={t('announcements.nobodyRead')} />
              </TabsContent>
            </Tabs>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function People({ people, empty }: { people: ReceiptPerson[]; empty: string }) {
  const fmt = useFormat()
  if (!people.length) return <p className="py-3 text-sm text-muted-foreground">{empty}</p>
  return (
    <ul className="mt-2 divide-y">
      {people.map((p) => (
        <li key={p.id} className="flex items-center gap-2.5 py-2 text-sm">
          <UserAvatar name={p.full_name} className="size-7" />
          <span className="min-w-0 flex-1">
            <bdi className="block truncate font-medium">{p.full_name}</bdi>
            {p.department && <bdi className="block truncate text-xs text-muted-foreground">{p.department}</bdi>}
          </span>
          {p.read_at && <span className="shrink-0 text-xs text-muted-foreground">{fmt.relative(p.read_at)}</span>}
        </li>
      ))}
    </ul>
  )
}
