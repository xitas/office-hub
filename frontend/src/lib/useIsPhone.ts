import { useSyncExternalStore } from 'react'

const QUERY = '(max-width: 767px), (pointer: coarse)'

/** True on phones and touch-first screens, where drag and drop gives way to menus and pickers. */
export function useIsPhone() {
  return useSyncExternalStore(
    (onChange) => {
      const media = window.matchMedia(QUERY)
      media.addEventListener('change', onChange)
      return () => media.removeEventListener('change', onChange)
    },
    () => window.matchMedia(QUERY).matches,
    () => false,
  )
}
