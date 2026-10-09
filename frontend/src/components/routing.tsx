import { Loader2, SearchX } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, Outlet, useLocation } from 'react-router-dom'
import { EmptyState } from '@/components/common'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/auth'
import { usePermission } from '@/lib/permissions'

/** Shown while the first lazily loaded page loads (React Router's hydrate fallback). */
export function FullPageFallback() {
  return <FullPageSpinner />
}

function FullPageSpinner() {
  return (
    <div className="flex min-h-dvh items-center justify-center">
      <Loader2 className="size-6 animate-spin text-muted-foreground" />
    </div>
  )
}

export function RequireAuth() {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <FullPageSpinner />
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  return <Outlet />
}

export function PublicOnly() {
  const { status } = useAuth()
  if (status === 'loading') return <FullPageSpinner />
  return <Outlet />
}

/** Renders "not found" rather than a forbidden page, so hidden modules are not advertised. */
export function RequirePermission({ perm, children }: { perm: string; children: ReactNode }) {
  return usePermission(perm) ? <>{children}</> : <NotFound />
}

export function Can({ perm, children, fallback = null }: { perm: string; children: ReactNode; fallback?: ReactNode }) {
  return usePermission(perm) ? <>{children}</> : <>{fallback}</>
}

export function NotFound() {
  const { t } = useTranslation()
  return (
    <div className="py-16">
      <EmptyState icon={SearchX} title={t('common.notFound')} hint={t('common.notFoundHint')} />
      <div className="mt-4 flex justify-center">
        <Button nativeButton={false} render={<Link to="/" />}>
          {t('common.goHome')}
        </Button>
      </div>
    </div>
  )
}
