import { Loader2, Upload } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { RoleBadge, TextField, UserAvatar } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { api, apiError } from '@/lib/api'
import { useAuth, useMe } from '@/lib/auth'
import type { Me } from '@/lib/types'

export function ProfileTab() {
  const { t } = useTranslation()
  const me = useMe()
  const { setUser } = useAuth()
  const fileRef = useRef<HTMLInputElement>(null)
  const [form, setForm] = useState({ full_name: me.full_name, phone: me.phone, job_title: me.job_title })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)

  const save = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErrors({})
    try {
      const { data } = await api.patch<Me>('/auth/me/', form)
      setUser(data)
      toast.success(t('common.saved'))
    } catch (err) {
      const info = apiError(err)
      setErrors(info.fields)
      toast.error(info.message)
    } finally {
      setBusy(false)
    }
  }

  const uploadAvatar = async (file: File) => {
    setUploading(true)
    try {
      const body = new FormData()
      body.append('avatar', file)
      const { data } = await api.patch<Me>('/auth/me/', body)
      setUser(data)
      toast.success(t('common.saved'))
    } catch (err) {
      toast.error(apiError(err).fields.avatar ?? apiError(err).message)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <Card>
      <form onSubmit={save} className="flex flex-col gap-4">
        <CardHeader>
          <CardTitle>{t('settings.profile')}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="flex items-center gap-4">
            <UserAvatar name={me.full_name} src={me.avatar} className="size-16" />
            <div className="grid gap-1">
              <Button type="button" variant="outline" size="sm" disabled={uploading} onClick={() => fileRef.current?.click()}>
                {uploading ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
                {t('settings.uploadPhoto')}
              </Button>
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && void uploadAvatar(e.target.files[0])}
              />
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              id="full_name"
              label={t('settings.fullName')}
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              error={errors.full_name}
              required
            />
            <TextField id="email" label={t('common.email')} value={me.email} disabled dir="ltr" />
            <TextField
              id="phone"
              label={t('common.phone')}
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
              error={errors.phone}
              dir="ltr"
              inputMode="tel"
            />
            <TextField
              id="job_title"
              label={t('common.jobTitle')}
              value={form.job_title}
              onChange={(e) => setForm({ ...form, job_title: e.target.value })}
              error={errors.job_title}
            />
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <RoleBadge role={me.role} />
            <span>·</span>
            <span>{me.department_name ?? t('common.noDepartment')}</span>
          </div>
        </CardContent>
        <CardFooter className="justify-end">
          <Button type="submit" disabled={busy}>
            {busy && <Loader2 className="size-4 animate-spin" />}
            {busy ? t('common.saving') : t('common.save')}
          </Button>
        </CardFooter>
      </form>
    </Card>
  )
}
