import { TriangleAlert } from 'lucide-react'
import { useCallback, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ConfirmContext, type ConfirmOptions } from '@/lib/confirm'

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  const [options, setOptions] = useState<ConfirmOptions | null>(null)
  const resolver = useRef<((ok: boolean) => void) | null>(null)

  const confirm = useCallback((opts: ConfirmOptions) => {
    resolver.current?.(false) // a newer prompt cancels any pending one
    setOptions(opts)
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve
    })
  }, [])

  const settle = (ok: boolean) => {
    resolver.current?.(ok)
    resolver.current = null
    setOptions(null)
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog open={options !== null} onOpenChange={(open) => !open && settle(false)}>
        <DialogContent showCloseButton={false} className="sm:max-w-md">
          {options && (
            <>
              <DialogHeader className="flex-row items-start gap-3">
                {options.destructive && (
                  <div className="shrink-0 rounded-full bg-destructive/10 p-2 text-destructive">
                    <TriangleAlert className="size-5" />
                  </div>
                )}
                <div className="grid gap-1.5 text-start">
                  <DialogTitle>{options.title}</DialogTitle>
                  {options.description && <DialogDescription>{options.description}</DialogDescription>}
                </div>
              </DialogHeader>
              <DialogFooter>
                <Button variant="outline" onClick={() => settle(false)}>
                  {options.cancelLabel ?? t('common.cancel')}
                </Button>
                <Button variant={options.destructive ? 'destructive' : 'default'} onClick={() => settle(true)} autoFocus>
                  {options.confirmLabel ?? t('common.confirm')}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </ConfirmContext.Provider>
  )
}
