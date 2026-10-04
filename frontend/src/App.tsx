import { DirectionProvider } from '@base-ui/react/direction-provider'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { RouterProvider } from 'react-router-dom'
import { ConfirmProvider } from '@/components/common/ConfirmProvider'
import { ThemeProvider } from '@/components/ThemeProvider'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { isRtl } from '@/i18n'
import { AuthProvider } from '@/lib/auth'
import { router } from '@/routes'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (count, error) => {
        const status = (error as { response?: { status?: number } }).response?.status
        return status !== undefined && status < 500 ? false : count < 2
      },
    },
  },
})

/** Keeps Base UI popups (menus, selects, sheets) aligned with the current text direction. */
function Direction({ children }: { children: ReactNode }) {
  const { i18n } = useTranslation()
  const dir = isRtl(i18n.language) ? 'rtl' : 'ltr'
  return <DirectionProvider direction={dir}>{children}</DirectionProvider>
}

export function App() {
  const { i18n } = useTranslation()

  // Server-rendered text (errors, notifications, audit labels) depends on the language: refetch on switch.
  useEffect(() => {
    const refetch = () => void queryClient.invalidateQueries()
    i18n.on('languageChanged', refetch)
    return () => i18n.off('languageChanged', refetch)
  }, [i18n])
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <Direction>
          <TooltipProvider>
            <AuthProvider>
              <ConfirmProvider>
                <RouterProvider router={router} />
              </ConfirmProvider>
              <Toaster position={isRtl(i18n.language) ? 'bottom-left' : 'bottom-right'} richColors closeButton />
            </AuthProvider>
          </TooltipProvider>
        </Direction>
      </QueryClientProvider>
    </ThemeProvider>
  )
}
