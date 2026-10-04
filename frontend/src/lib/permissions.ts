import { useAuth } from './auth'

/** Permission strings come from the backend matrix as "module.action", e.g. "users.create". */
export function usePermission(permission: string | undefined): boolean {
  const { user } = useAuth()
  if (!permission) return true
  return !!user?.permissions.includes(permission)
}
