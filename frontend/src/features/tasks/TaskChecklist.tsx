import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, GripVertical, ListChecks, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState, type DragEvent, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { api, apiError } from '@/lib/api'
import { usePermission } from '@/lib/permissions'
import type { ChecklistItem } from '@/lib/tasks'
import { cn } from '@/lib/utils'

/** The task's checklist: anyone who can see the task ticks items; changing them needs edit rights. */
export function TaskChecklist({ taskId }: { taskId: number }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const canEdit = usePermission('tasks.edit')
  const key = ['tasks', 'checklist', taskId]
  const base = `/tasks/${taskId}/checklist/`
  const [text, setText] = useState('')
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [dragging, setDragging] = useState<number | null>(null)

  const { data: items, isLoading } = useQuery({
    queryKey: key,
    queryFn: async () => (await api.get<ChecklistItem[]>(base)).data,
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: key })
    void queryClient.invalidateQueries({ queryKey: ['tasks', 'activity', taskId] })
    void queryClient.invalidateQueries({ queryKey: ['tasks', 'list'] })
    void queryClient.invalidateQueries({ queryKey: ['tasks', 'board'] })
    void queryClient.invalidateQueries({ queryKey: ['tasks', 'detail', String(taskId)] })
  }
  const onError = (err: unknown) => {
    toast.error(apiError(err).message)
    refresh()
  }

  const add = useMutation({
    mutationFn: async (value: string) => (await api.post<ChecklistItem>(base, { text: value })).data,
    onSuccess: () => {
      setText('')
      refresh()
    },
    onError,
  })
  const update = useMutation({
    mutationFn: async ({ id, ...body }: { id: number; done?: boolean; text?: string }) =>
      (await api.patch<ChecklistItem>(`${base}${id}/`, body)).data,
    onMutate: ({ id, ...body }) => queryClient.setQueryData<ChecklistItem[]>(key, (old) => old?.map((i) => (i.id === id ? { ...i, ...body } : i))),
    onSuccess: refresh,
    onError,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`${base}${id}/`),
    onMutate: (id) => queryClient.setQueryData<ChecklistItem[]>(key, (old) => old?.filter((i) => i.id !== id)),
    onSuccess: refresh,
    onError,
  })
  const reorder = useMutation({
    mutationFn: async (order: number[]) => (await api.post<ChecklistItem[]>(`${base}reorder/`, { order })).data,
    onMutate: (order) =>
      queryClient.setQueryData<ChecklistItem[]>(key, (old) => (old ? order.map((id) => old.find((i) => i.id === id)!).filter(Boolean) : old)),
    onSuccess: (data) => queryClient.setQueryData(key, data),
    onError,
  })

  const move = (id: number, to: number) => {
    if (!items) return
    const order = items.map((i) => i.id).filter((i) => i !== id)
    order.splice(Math.max(0, Math.min(to, order.length)), 0, id)
    reorder.mutate(order)
  }
  const onDrop = (e: DragEvent, targetIndex: number) => {
    e.preventDefault()
    if (dragging !== null) move(dragging, targetIndex)
    setDragging(null)
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (text.trim()) add.mutate(text.trim())
  }
  const saveEdit = (item: ChecklistItem) => {
    const value = draft.trim()
    setEditing(null)
    if (value && value !== item.text) update.mutate({ id: item.id, text: value })
  }

  const done = items?.filter((i) => i.done).length ?? 0
  const total = items?.length ?? 0

  return (
    <Card>
      <CardHeader className="gap-2">
        <div className="flex items-center gap-2">
          <ListChecks className="size-4 text-muted-foreground" />
          <CardTitle className="flex-1">{t('tasks.checklist.title')}</CardTitle>
          {total > 0 && <span className="text-sm text-muted-foreground font-latin">{t('tasks.checklist.progress', { done, total })}</span>}
        </div>
        {total > 0 && (
          <div className="h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} aria-label={t('tasks.checklist.title')}>
            <div className="h-full rounded-full bg-success transition-[width]" style={{ width: `${(done / total) * 100}%` }} />
          </div>
        )}
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-2">
        {isLoading ? (
          <Skeleton className="h-16" />
        ) : (
          items &&
          items.length > 0 && (
            <ol className="grid grid-cols-1 gap-0.5">
              {items.map((item, index) => (
                <li
                  key={item.id}
                  draggable={canEdit && editing !== item.id}
                  onDragStart={(e) => {
                    e.dataTransfer.effectAllowed = 'move'
                    e.dataTransfer.setData('text/plain', String(item.id))
                    setDragging(item.id)
                  }}
                  onDragEnd={() => setDragging(null)}
                  onDragOver={(e) => {
                    if (dragging !== null && dragging !== item.id) e.preventDefault()
                  }}
                  onDrop={(e) => onDrop(e, index)}
                  className={cn('group flex items-center gap-2 rounded-md px-1 py-1 hover:bg-muted/50', dragging === item.id && 'opacity-40')}
                >
                  {canEdit && <GripVertical className="hidden size-4 shrink-0 cursor-grab text-muted-foreground/60 md:block" aria-hidden />}
                  <Checkbox
                    checked={item.done}
                    onCheckedChange={(v) => update.mutate({ id: item.id, done: v === true })}
                    aria-label={t(item.done ? 'tasks.checklist.untick' : 'tasks.checklist.tick', { text: item.text })}
                  />
                  {editing === item.id ? (
                    <Input
                      autoFocus
                      value={draft}
                      maxLength={300}
                      onChange={(e) => setDraft(e.target.value)}
                      onBlur={() => saveEdit(item)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') saveEdit(item)
                        if (e.key === 'Escape') setEditing(null)
                      }}
                      aria-label={t('tasks.checklist.editItem')}
                      className="h-8 flex-1"
                    />
                  ) : (
                    <span dir="auto" className={cn('min-w-0 flex-1 text-sm break-words', item.done && 'text-muted-foreground line-through')}>
                      {item.text}
                    </span>
                  )}
                  {canEdit && editing !== item.id && (
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={<Button variant="ghost" size="icon-sm" className="shrink-0" aria-label={t('tasks.checklist.itemActions', { text: item.text })} />}
                      >
                        <MoreHorizontal className="size-4" />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-44">
                        <DropdownMenuItem
                          onClick={() => {
                            setDraft(item.text)
                            setEditing(item.id)
                          }}
                        >
                          <Pencil className="size-4" />
                          {t('common.edit')}
                        </DropdownMenuItem>
                        <DropdownMenuItem disabled={index === 0} onClick={() => move(item.id, index - 1)}>
                          <ArrowUp className="size-4" />
                          {t('tasks.checklist.moveUp')}
                        </DropdownMenuItem>
                        <DropdownMenuItem disabled={index === items.length - 1} onClick={() => move(item.id, index + 1)}>
                          <ArrowDown className="size-4" />
                          {t('tasks.checklist.moveDown')}
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem variant="destructive" onClick={() => remove.mutate(item.id)}>
                          <Trash2 className="size-4" />
                          {t('common.delete')}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </li>
              ))}
            </ol>
          )
        )}
        {!isLoading && total === 0 && !canEdit && <p className="text-sm text-muted-foreground">{t('tasks.checklist.empty')}</p>}
        {canEdit && (
          <form onSubmit={submit} className="flex gap-2">
            <Input
              value={text}
              maxLength={300}
              onChange={(e) => setText(e.target.value)}
              placeholder={t('tasks.checklist.addPlaceholder')}
              aria-label={t('tasks.checklist.addPlaceholder')}
            />
            <Button type="submit" variant="outline" disabled={!text.trim() || add.isPending}>
              <Plus className="size-4" />
              {t('tasks.checklist.add')}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  )
}
