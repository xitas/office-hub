import { Loader2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { TextField } from '@/components/common'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { apiError } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { AuthLayout } from './AuthLayout'

export function LoginPage() {
  const { t } = useTranslation()
  const { status, login, verifyOtp } = useAuth()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [otpToken, setOtpToken] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (status === 'authenticated') return <Navigate to={from} replace />

  const submitPassword = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await login(email.trim(), password)
      if (result.otpRequired) setOtpToken(result.otpToken)
    } catch (err) {
      setError(apiError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const submitCode = async (e: FormEvent) => {
    e.preventDefault()
    if (!otpToken) return
    setBusy(true)
    setError(null)
    try {
      await verifyOtp(otpToken, code.trim())
    } catch (err) {
      setError(apiError(err).message)
      setCode('')
    } finally {
      setBusy(false)
    }
  }

  if (otpToken) {
    return (
      <AuthLayout title={t('auth.twoFactorTitle')} subtitle={t('auth.twoFactorSubtitle')}>
        <form onSubmit={submitCode} className="grid gap-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <TextField
            id="code"
            label={t('auth.code')}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            inputMode="text"
            autoComplete="one-time-code"
            autoFocus
            required
            className="font-latin"
            dir="ltr"
            placeholder="123456"
          />
          <Button type="submit" disabled={busy || code.trim().length < 6}>
            {busy && <Loader2 className="size-4 animate-spin" />}
            {t('auth.verify')}
          </Button>
          <Button
            type="button"
            variant="link"
            onClick={() => {
              setOtpToken(null)
              setCode('')
              setError(null)
            }}
          >
            {t('auth.backToSignIn')}
          </Button>
        </form>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title={t('auth.welcome')} subtitle={t('auth.subtitle')}>
      <form onSubmit={submitPassword} className="grid gap-4">
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
          autoComplete="username"
          autoFocus
          required
          dir="ltr"
        />
        <div className="grid gap-1.5">
          <TextField
            id="password"
            type="password"
            label={t('auth.password')}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            dir="ltr"
          />
          <Link to="/forgot-password" className="justify-self-end text-xs text-primary hover:underline">
            {t('auth.forgotPassword')}
          </Link>
        </div>
        <Button type="submit" disabled={busy}>
          {busy && <Loader2 className="size-4 animate-spin" />}
          {busy ? t('auth.signingIn') : t('auth.signIn')}
        </Button>
      </form>
    </AuthLayout>
  )
}
