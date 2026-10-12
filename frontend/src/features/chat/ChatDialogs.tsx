import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { EmptyState, FormDialog, FormField, SimpleSelect, TextField, UserAvatar } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { api, apiError } from '@/lib/api'
import { useMe } from '@/lib/auth'
import { CONVERSATIONS_KEY, conversationTitle, type Conversation } from '@/lib/chat'
import { useDepartments, useUserOptions } from '@/lib/queries'
import { ChannelIcon } from './ChatPage'

interface DialogProps {
  onClose: () => void
  onOpened: (conversation: Conversation) => void
}

function SearchBox({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <label className="flex items-center gap-2 rounded-md border bg-background px-2">
      <Search className="size-4 text-muted-foreground" />
      <input
        autoFocus
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={label}
        aria-label={label}
        className="h-9 min-w-0 flex-1 bg-transparent text-sm outline-none"
      />
    </label>
  )
}

/** Start (or reopen) a direct message with any colleague. */
export function NewMessageDialog({ onClose, onOpened }: DialogProps) {
  const { t } = useTranslation()
  const me = useMe()
  const queryClient = useQueryClient()
  const { data: users, isLoading } = useUserOptions()
  const [q, setQ] = useState('')
  const open = useMutation({
    mutationFn: async (user: number) => (await api.post<Conversation>('/chat/conversations/direct/', { user })).data,
    onSuccess: (c) => {
      void queryClient.invalidateQueries({ queryKey: [...CONVERSATIONS_KEY, 'mine'] })
      onOpened(c)
    },
    onError: (e) => toast.error(apiError(e).message),
  })
  const people = (users ?? []).filter((u) => u.id !== me.id && `${u.full_name} ${u.email}`.toLowerCase().includes(q.trim().toLowerCase()))

  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={t('chat.newMessage')} description={t('chat.newMessageHint')}>
      <div className="grid gap-3">
        <SearchBox value={q} onChange={setQ} label={t('chat.findPerson')} />
        {isLoading ? (
          <Skeleton className="h-40" />
        ) : (
          <ul className="max-h-80 overflow-y-auto">
            {people.map((u) => (
              <li key={u.id}>
                <button
                  type="button"
                  disabled={open.isPending}
                  onClick={() => open.mutate(u.id)}
                  className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-start hover:bg-muted"
                >
                  <UserAvatar name={u.full_name} src={u.avatar} className="size-8" />
                  <span className="min-w-0 flex-1">
                    <bdi className="block truncate text-sm font-medium">{u.full_name}</bdi>
                    <span className="block truncate text-xs text-muted-foreground">{[u.job_title, u.department_name].filter(Boolean).join(' · ')}</span>
                  </span>
                </button>
              </li>
            ))}
            {!people.length && <li className="py-6 text-center text-sm text-muted-foreground">{t('chat.noPeople')}</li>}
          </ul>
        )}
      </div>
    </FormDialog>
  )
}

/** Channels you can see but haven't joined: open to read, join to write. */
export function BrowseChannelsDialog({ onClose, onOpened }: DialogProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [q, setQ] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: [...CONVERSATIONS_KEY, 'browse'],
    queryFn: async () => (await api.get<Conversation[]>('/chat/conversations/', { params: { scope: 'browse' } })).data,
  })
  const join = useMutation({
    mutationFn: async (id: number) => (await api.post<Conversation>(`/chat/conversations/${id}/join/`)).data,
    onSuccess: (c) => {
      void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_KEY })
      onOpened(c)
    },
    onError: (e) => toast.error(apiError(e).message),
  })
  const channels = (data ?? []).filter((c) => conversationTitle(c, t).toLowerCase().includes(q.trim().toLowerCase()))

  return (
    <FormDialog open onOpenChange={(o) => !o && onClose()} title={t('chat.browse')} description={t('chat.browseHint')}>
      <div className="grid gap-3">
        <SearchBox value={q} onChange={setQ} label={t('chat.filter')} />
        {isLoading ? (
          <Skeleton className="h-32" />
        ) : !channels.length ? (
          <EmptyState icon={Search} title={t('chat.noChannels')} className="py-6" />
        ) : (
          <ul className="max-h-80 divide-y overflow-y-auto">
            {channels.map((c) => (
              <li key={c.id} className="flex items-center gap-3 py-2">
                <ChannelIcon conversation={c} />
                <span className="min-w-0 flex-1">
                  <bdi className="block truncate text-sm font-medium">{conversationTitle(c, t)}</bdi>
                  <span className="block truncate text-xs text-muted-foreground">
                    {t('chat.members', { count: c.member_count })}
                    {c.description && <> · <bdi>{c.description}</bdi></>}
                  </span>
                </span>
                <Button size="sm" variant="outline" onClick={() => onOpened(c)}>
                  {t('chat.open')}
                </Button>
                {!c.is_private && (
                  <Button size="sm" onClick={() => join.mutate(c.id)} disabled={join.isPending}>
                    {t('chat.join')}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </FormDialog>
  )
}

/** Admins: any channel. Managers: channels for their own department. */
export function NewChannelDialog({ onClose, onOpened }: DialogProps) {
  const { t } = useTranslation()
  const me = useMe()
  const queryClient = useQueryClient()
  const isAdmin = me.role === 'admin'
  const { data: departments } = useDepartments()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [isPrivate, setPrivate] = useState(false)
  const [type, setType] = useState<'project' | 'department' | 'general'>('project')
  const [department, setDepartment] = useState<string>(me.department ? String(me.department) : '')
  const [errors, setErrors] = useState<Record<string, string>>({})

  const create = useMutation({
    mutationFn: async () =>
      (
        await api.post<Conversation>('/chat/conversations/', {
          name,
          description,
          is_private: isPrivate,
          channel_type: type,
          ...(isAdmin ? { department: department ? Number(department) : null } : {}),
        })
      ).data,
    onSuccess: (c) => {
      void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_KEY })
      toast.success(t('chat.channelCreated', { name: c.name }))
      onOpened(c)
    },
    onError: (e) => {
      const info = apiError(e)
      setErrors(info.fields)
      if (!Object.keys(info.fields).length) toast.error(info.message)
    },
  })

  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={t('chat.newChannel')}
      description={isAdmin ? undefined : t('chat.newChannelManagerHint')}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => create.mutate()} disabled={!name.trim() || create.isPending}>
            {t('chat.createChannel')}
          </Button>
        </>
      }
    >
      <form
        className="grid gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) create.mutate()
        }}
      >
        <TextField id="ch-name" label={t('chat.channelName')} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} required maxLength={80} />
        <TextField id="ch-desc" label={t('chat.channelDescription')} value={description} onChange={(e) => setDescription(e.target.value)} error={errors.description} maxLength={300} />
        {isAdmin && (
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField id="ch-type" label={t('chat.channelType')} error={errors.channel_type}>
              <SimpleSelect
                id="ch-type"
                value={type}
                onChange={(v) => setType(v as typeof type)}
                options={(['project', 'department', 'general'] as const).map((v) => ({ value: v, label: t(`chat.types.${v}`) }))}
              />
            </FormField>
            <FormField id="ch-dept" label={t('chat.department')} error={errors.department}>
              <SimpleSelect
                id="ch-dept"
                value={department}
                onChange={setDepartment}
                options={[{ value: '', label: t('chat.noDepartment') }, ...(departments ?? []).map((d) => ({ value: String(d.id), label: d.name }))]}
              />
            </FormField>
          </div>
        )}
        <div className="flex items-start justify-between gap-4 rounded-lg border p-3">
          <div>
            <Label htmlFor="ch-private">{t('chat.private')}</Label>
            <p className="text-xs text-muted-foreground">{t('chat.privateHint')}</p>
          </div>
          <Switch id="ch-private" checked={isPrivate} onCheckedChange={setPrivate} />
        </div>
        {errors.non_field_errors && <p className="text-sm text-destructive">{errors.non_field_errors}</p>}
      </form>
    </FormDialog>
  )
}
