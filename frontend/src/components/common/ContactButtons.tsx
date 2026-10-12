import { Mail, MessageCircle, Phone } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { rememberContactAttempt } from '@/lib/quickLog'
import { whatsappNumber } from '@/lib/queries'
import type { Picked } from './RecordPicker'

/** Click-to-call, click-to-WhatsApp and email buttons (Team, Companies, Contacts). */
export function ContactButtons({
  phone,
  whatsapp,
  email,
  className,
  logFor,
}: {
  phone?: string
  /** Separate WhatsApp number; falls back to `phone`. */
  whatsapp?: string
  email?: string
  className?: string
  /** A contact or company: after calling or messaging, the app offers to log it on return. */
  logFor?: Picked
}) {
  const { t } = useTranslation()
  const wa = whatsapp || phone
  if (!phone && !wa && !email) return null
  return (
    <div className={className ?? 'flex flex-wrap gap-2'}>
      {phone && (
        <Button
          variant="outline"
          size="sm"
          nativeButton={false}
          render={<a href={`tel:${phone.replace(/\s/g, '')}`} onClick={() => logFor && rememberContactAttempt('call', logFor)} />}
        >
          <Phone className="size-3.5" />
          {t('team.call')}
        </Button>
      )}
      {wa && (
        <Button
          variant="outline"
          size="sm"
          nativeButton={false}
          render={
            <a
              href={`https://wa.me/${whatsappNumber(wa)}`}
              target="_blank"
              rel="noreferrer"
              onClick={() => logFor && rememberContactAttempt('whatsapp', logFor)}
            />
          }
        >
          <MessageCircle className="size-3.5" />
          {t('team.whatsapp')}
        </Button>
      )}
      {email && (
        <Button variant="outline" size="sm" nativeButton={false} render={<a href={`mailto:${email}`} />}>
          <Mail className="size-3.5" />
          {t('team.sendEmail')}
        </Button>
      )}
    </div>
  )
}
