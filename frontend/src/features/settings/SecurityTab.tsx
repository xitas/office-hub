import { Check, Copy, Loader2, ShieldCheck, ShieldOff } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { FormDialog, TextField } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { api, apiError } from '@/lib/api'
import { useAuth, useMe } from '@/lib/auth'

export function SecurityTab() {
  return (
    <div className="grid gap-4">
      <TwoFactorCard />
      <ChangePasswordCard />
    </div>
  )
}

function ChangePasswordCard() {
  const { t } = useTranslation()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErrors({})
    try {
      await api.post('/auth/password/change/', { current_password: current, new_password: next })
      setCurrent('')
      setNext('')
      toast.success(t('settings.passwordChanged'))
    } catch (err) {
      setErrors(apiError(err).fields)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <CardHeader>
          <CardTitle>{t('settings.changePassword')}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <TextField
            id="current_password"
            type="password"
            label={t('settings.currentPassword')}
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            error={errors.current_password}
            autoComplete="current-password"
            required
            dir="ltr"
          />
          <TextField
            id="new_password"
            type="password"
            label={t('settings.newPassword')}
            value={next}
            onChange={(e) => setNext(e.target.value)}
            error={errors.new_password}
            autoComplete="new-password"
            required
            dir="ltr"
          />
        </CardContent>
        <CardFooter className="justify-end">
          <Button type="submit" disabled={busy}>
            {busy && <Loader2 className="size-4 animate-spin" />}
            {t('settings.updatePassword')}
          </Button>
        </CardFooter>
      </form>
    </Card>
  )
}

type Step = 'idle' | 'scan' | 'codes' | 'disable' | 'regenerate'

function TwoFactorCard() {
  const { t } = useTranslation()
  const me = useMe()
  const { reloadUser } = useAuth()
  const [step, setStep] = useState<Step>('idle')
  const [setup, setSetup] = useState<{ secret: string; qr_code: string } | null>(null)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [codes, setCodes] = useState<string[]>([])
  const [error, setError] = useState<string | undefined>()
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  const reset = () => {
    setStep('idle')
    setSetup(null)
    setCode('')
    setPassword('')
    setError(undefined)
    setCopied(false)
  }

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(undefined)
    try {
      await fn()
    } catch (err) {
      const info = apiError(err)
      setError(info.fields.code ?? info.fields.password ?? info.message)
    } finally {
      setBusy(false)
    }
  }

  const startSetup = () =>
    run(async () => {
      const { data } = await api.post<{ secret: string; qr_code: string }>('/auth/2fa/setup/')
      setSetup(data)
      setStep('scan')
    })

  const confirmEnable = (e: FormEvent) => {
    e.preventDefault()
    return run(async () => {
      const { data } = await api.post<{ backup_codes: string[] }>('/auth/2fa/enable/', { code: code.trim() })
      setCodes(data.backup_codes)
      setStep('codes')
      await reloadUser()
    })
  }

  const confirmDisable = (e: FormEvent) => {
    e.preventDefault()
    return run(async () => {
      await api.post('/auth/2fa/disable/', { password })
      await reloadUser()
      reset()
      toast.success(t('common.saved'))
    })
  }

  const regenerate = (e: FormEvent) => {
    e.preventDefault()
    return run(async () => {
      const { data } = await api.post<{ backup_codes: string[] }>('/auth/2fa/backup-codes/', { password })
      setPassword('')
      setCodes(data.backup_codes)
      setStep('codes')
    })
  }

  const copyCodes = async () => {
    await navigator.clipboard.writeText(codes.join('\n'))
    setCopied(true)
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle className="flex-1">{t('settings.twoFactor')}</CardTitle>
          <Badge variant={me.two_factor_enabled ? 'default' : 'secondary'}>
            {me.two_factor_enabled ? t('common.active') : t('common.inactive')}
          </Badge>
        </div>
        <CardDescription>{me.two_factor_enabled ? t('settings.twoFactorOn') : t('settings.twoFactorOff')}</CardDescription>
      </CardHeader>
      <CardFooter className="flex-wrap justify-end gap-2">
        {me.two_factor_enabled ? (
          <>
            <Button variant="outline" onClick={() => setStep('regenerate')}>
              {t('settings.regenerateCodes')}
            </Button>
            <Button variant="destructive" onClick={() => setStep('disable')}>
              <ShieldOff className="size-4" />
              {t('settings.disable2fa')}
            </Button>
          </>
        ) : (
          <Button onClick={() => void startSetup()} disabled={busy}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <ShieldCheck className="size-4" />}
            {t('settings.enable2fa')}
          </Button>
        )}
      </CardFooter>

      <FormDialog open={step === 'scan'} onOpenChange={(o) => !o && reset()} title={t('settings.enable2fa')}>
        {setup && (
          <form onSubmit={confirmEnable} className="grid gap-4">
            <p className="text-sm text-muted-foreground">{t('settings.scanQr')}</p>
            <img src={setup.qr_code} alt="" className="mx-auto size-48 rounded-lg bg-white p-2" />
            <div className="text-xs text-muted-foreground">
              {t('settings.manualKey')}
              <code className="mt-1 block rounded bg-muted p-2 text-center text-sm break-all text-foreground font-latin" dir="ltr">
                {setup.secret}
              </code>
            </div>
            <TextField
              id="totp"
              label={t('settings.enterCode')}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              error={error}
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              dir="ltr"
              className="font-latin"
            />
            <Button type="submit" disabled={busy || code.trim().length < 6}>
              {busy && <Loader2 className="size-4 animate-spin" />}
              {t('auth.verify')}
            </Button>
          </form>
        )}
      </FormDialog>

      <FormDialog
        open={step === 'codes'}
        onOpenChange={(o) => !o && reset()}
        title={t('settings.backupTitle')}
        description={t('settings.backupHint')}
        footer={
          <>
            <Button variant="outline" onClick={() => void copyCodes()}>
              {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
              {copied ? t('settings.copied') : t('settings.copyCodes')}
            </Button>
            <Button onClick={reset}>{t('settings.done')}</Button>
          </>
        }
      >
        <ul className="grid grid-cols-2 gap-2 rounded-lg bg-muted p-3 text-center text-sm font-latin" dir="ltr">
          {codes.map((c) => (
            <li key={c} className="font-mono">
              {c}
            </li>
          ))}
        </ul>
      </FormDialog>

      <FormDialog
        open={step === 'disable' || step === 'regenerate'}
        onOpenChange={(o) => !o && reset()}
        title={step === 'disable' ? t('settings.disable2fa') : t('settings.regenerateCodes')}
        description={t('settings.confirmWithPassword')}
      >
        <form onSubmit={step === 'disable' ? confirmDisable : regenerate} className="grid gap-4">
          <TextField
            id="confirm-password"
            type="password"
            label={t('auth.password')}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={error}
            autoComplete="current-password"
            autoFocus
            required
            dir="ltr"
          />
          <Button type="submit" variant={step === 'disable' ? 'destructive' : 'default'} disabled={busy}>
            {busy && <Loader2 className="size-4 animate-spin" />}
            {t('common.confirm')}
          </Button>
        </form>
      </FormDialog>
    </Card>
  )
}
