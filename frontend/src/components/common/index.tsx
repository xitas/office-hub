import type { LucideIcon } from 'lucide-react'
import { AlertCircle, Inbox } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { Role } from '@/lib/types'

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  hint,
  className,
}: {
  icon?: LucideIcon
  title: string
  hint?: string
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-2 py-8 text-center', className)}>
      <div className="rounded-full bg-muted p-3 text-muted-foreground">
        <Icon className="size-5" />
      </div>
      <p className="text-sm font-medium">{title}</p>
      {hint && <p className="max-w-xs text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col items-center gap-3 py-10 text-center">
      <AlertCircle className="size-6 text-destructive" />
      <p className="text-sm">{message ?? t('common.errorTitle')}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      )}
    </div>
  )
}

export function FormField({
  id,
  label,
  error,
  hint,
  children,
  className,
}: {
  id: string
  label: string
  error?: string
  hint?: string
  children?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('grid gap-1.5', className)}>
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && !error && <p className="text-xs text-muted-foreground">{hint}</p>}
      {error && (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}

export function TextField({
  id,
  label,
  error,
  hint,
  className,
  ...inputProps
}: { id: string; label: string; error?: string; hint?: string } & React.ComponentProps<typeof Input>) {
  return (
    <FormField id={id} label={label} error={error} hint={hint} className={className}>
      <Input id={id} aria-invalid={!!error} aria-describedby={error ? `${id}-error` : undefined} {...inputProps} />
    </FormField>
  )
}

export interface Option {
  value: string
  label: string
}

/** Thin wrapper over the Base UI select so pages pass plain options. */
export function SimpleSelect({
  id,
  value,
  onChange,
  options,
  placeholder,
  className,
  disabled,
}: {
  id?: string
  value: string
  onChange: (value: string) => void
  options: Option[]
  placeholder?: string
  className?: string
  disabled?: boolean
}) {
  return (
    <Select
      value={value}
      onValueChange={(v) => onChange((v as string | null) ?? '')}
      items={options}
      disabled={disabled}
    >
      <SelectTrigger id={id} className={cn('w-full', className)}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

/** Dialog that becomes a full-screen sheet on phones. */
export function FormDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg max-sm:inset-0 max-sm:max-h-dvh max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-none max-sm:rtl:translate-x-0 max-sm:content-start">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        {children}
        {footer && <DialogFooter>{footer}</DialogFooter>}
      </DialogContent>
    </Dialog>
  )
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('')
}

export function UserAvatar({ name, src, className }: { name: string; src?: string | null; className?: string }) {
  return (
    <Avatar className={className}>
      {src && <AvatarImage src={src} alt="" />}
      <AvatarFallback className="bg-primary/10 text-xs font-medium text-primary font-latin">{initials(name)}</AvatarFallback>
    </Avatar>
  )
}

const ROLE_STYLES: Record<Role, string> = {
  admin: 'bg-primary/10 text-primary border-primary/20',
  manager: 'bg-warning/15 text-foreground border-warning/30',
  staff: 'bg-muted text-muted-foreground',
}

export function RoleBadge({ role }: { role: Role }) {
  const { t } = useTranslation()
  return (
    <Badge variant="outline" className={ROLE_STYLES[role]}>
      {t(`roles.${role}`)}
    </Badge>
  )
}

export function Pagination({
  page,
  count,
  pageSize = 25,
  onPage,
}: {
  page: number
  count: number
  pageSize?: number
  onPage: (page: number) => void
}) {
  const { t } = useTranslation()
  const total = Math.max(1, Math.ceil(count / pageSize))
  if (total <= 1) return null
  return (
    <div className="mt-4 flex items-center justify-between gap-2 text-sm">
      <span className="text-muted-foreground">{t('common.pageOf', { page, total })}</span>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          {t('common.previous')}
        </Button>
        <Button variant="outline" size="sm" disabled={page >= total} onClick={() => onPage(page + 1)}>
          {t('common.next')}
        </Button>
      </div>
    </div>
  )
}
