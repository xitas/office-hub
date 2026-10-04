import { CheckCircle2, Loader2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { TextField } from '@/components/common'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { api, apiError } from '@/lib/api'
import { AuthLayout } from './AuthLayout'

export function ForgotPasswordPage() {
  const { t } = useTranslation()
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post('/auth/password/reset/', { email: email.trim() })
      setSent(true)
    } catch (err) {
      setError(apiError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout title={t('auth.resetTitle')} subtitle={t('auth.resetSubtitle')}>
      {sent ? (
        <div className="grid gap-4">
          <Alert>
            <CheckCircle2 className="size-4" />
            <AlertDescription>{t('auth.linkSent')}</AlertDescription>
          </Alert>
          <Button variant="outline" nativeButton={false} render={<Link to="/login" />}>
            {t('auth.backToSignIn')}
          </Button>
        </div>
      ) : (
        <form onSubmit={submit} className="grid gap-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <TextField
            id="email"
            type="email"
            label={t('auth.email')}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
            dir="ltr"
          />
          <Button type="submit" disabled={busy}>
            {busy && <Loader2 className="size-4 animate-spin" />}
            {t('auth.sendLink')}
          </Button>
          <Button variant="link" nativeButton={false} render={<Link to="/login" />}>
            {t('auth.backToSignIn')}
          </Button>
        </form>
      )}
    </AuthLayout>
  )
}

export function ResetPasswordPage() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const uid = params.get('uid')
  const token = params.get('token')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldError, setFieldError] = useState<string | undefined>()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setFieldError(undefined)
    if (password !== confirm) {
      setFieldError(t('auth.passwordsDontMatch'))
      return
    }
    setBusy(true)
    try {
      await api.post('/auth/password/reset/confirm/', { uid, token, new_password: password })
      setDone(true)
    } catch (err) {
      const info = apiError(err)
      setFieldError(info.fields.new_password)
      setError(info.fields.token ?? (info.fields.new_password ? null : info.message))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout title={t('auth.newPasswordTitle')}>
      {!uid || !token ? (
        <div className="grid gap-4">
          <Alert variant="destructive">
            <AlertDescription>{t('auth.invalidLink')}</AlertDescription>
          </Alert>
          <Button variant="outline" nativeButton={false} render={<Link to="/forgot-password" />}>
            {t('auth.sendLink')}
          </Button>
        </div>
      ) : done ? (
        <div className="grid gap-4">
          <Alert>
            <CheckCircle2 className="size-4" />
            <AlertDescription>{t('auth.passwordResetDone')}</AlertDescription>
          </Alert>
          <Button nativeButton={false} render={<Link to="/login" />}>{t('auth.signIn')}</Button>
        </div>
      ) : (
        <form onSubmit={submit} className="grid gap-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <TextField
            id="new-password"
            type="password"
            label={t('auth.newPassword')}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            required
            dir="ltr"
          />
          <TextField
            id="confirm-password"
            type="password"
            label={t('auth.confirmPassword')}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            required
            error={fieldError}
            dir="ltr"
          />
          <Button type="submit" disabled={busy}>
            {busy && <Loader2 className="size-4 animate-spin" />}
            {t('auth.setPassword')}
          </Button>
        </form>
      )}
    </AuthLayout>
  )
}
