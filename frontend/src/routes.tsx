import type { ComponentType } from 'react'
import { createBrowserRouter, Outlet } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { NotFound, PublicOnly, RequireAuth, RequirePermission } from '@/components/routing'
import { LoginPage } from '@/features/auth/LoginPage'
import { ForgotPasswordPage, ResetPasswordPage } from '@/features/auth/PasswordResetPages'
import { DashboardPage } from '@/features/dashboard/DashboardPage'

/** Admin-only section: the guard renders "not found" for anyone without the permission. */
const guarded = (perm: string, path: string, load: () => Promise<{ Component: ComponentType }>) => ({
  element: (
    <RequirePermission perm={perm}>
      <Outlet />
    </RequirePermission>
  ),
  children: [{ path, lazy: load }],
})

// Secondary pages are code-split; React Router keeps the current page visible while they load.
export const router = createBrowserRouter([
  {
    element: <PublicOnly />,
    children: [
      { path: '/login', element: <LoginPage /> },
      { path: '/forgot-password', element: <ForgotPasswordPage /> },
      { path: '/reset-password', element: <ResetPasswordPage /> },
    ],
  },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: 'team', lazy: () => import('@/features/team/TeamPage').then((m) => ({ Component: m.TeamPage })) },
          {
            path: 'notifications',
            lazy: () => import('@/features/notifications/NotificationsPage').then((m) => ({ Component: m.NotificationsPage })),
          },
          { path: 'settings', lazy: () => import('@/features/settings/SettingsPage').then((m) => ({ Component: m.SettingsPage })) },
          guarded('users.create', 'admin/users', () =>
            import('@/features/admin/UsersPage').then((m) => ({ Component: m.UsersPage })),
          ),
          guarded('departments.create', 'admin/departments', () =>
            import('@/features/admin/DepartmentsPage').then((m) => ({ Component: m.DepartmentsPage })),
          ),
          guarded('settings.edit', 'admin/organization', () =>
            import('@/features/admin/OrganizationPage').then((m) => ({ Component: m.OrganizationPage })),
          ),
          guarded('audit.view', 'admin/audit-log', () =>
            import('@/features/admin/AuditLogPage').then((m) => ({ Component: m.AuditLogPage })),
          ),
          { path: '*', element: <NotFound /> },
        ],
      },
    ],
  },
])
