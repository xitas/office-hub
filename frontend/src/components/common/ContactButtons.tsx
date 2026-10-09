import { Mail, MessageCircle, Phone } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { whatsappNumber } from '@/lib/queries'

/** Click-to-call, click-to-WhatsApp and email buttons (Team, Companies, Contacts). */
export function ContactButtons({
  phone,
  whatsapp,
  email,
  className,
}: {
  phone?: string
  /** Separate WhatsApp number; falls back to `phone`. */
  whatsapp?: string
  email?: string
  className?: string
}) {
  const { t } = useTranslation()
  const wa = whatsapp || phone
  if (!phone && !wa && !email) return null
  return (
    <div className={className ?? 'flex flex-wrap gap-2'}>
      {phone && (
        <Button variant="outline" size="sm" nativeButton={false} render={<a href={`tel:${phone.replace(/\s/g, '')}`} />}>
          <Phone className="size-3.5" />
          {t('team.call')}
        </Button>
      )}
      {wa && (
        <Button
          variant="outline"
          size="sm"
          nativeButton={false}
          render={<a href={`https://wa.me/${whatsappNumber(wa)}`} target="_blank" rel="noreferrer" />}
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
