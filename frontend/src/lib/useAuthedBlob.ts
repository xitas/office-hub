import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api } from './api'

/**
 * One object URL per downloaded file, shared by everything showing it, revoked a moment after the last of them
 * unmounts. (A URL per component, revoked on unmount, broke under StrictMode's extra cleanup: a cached file shown a
 * second time, e.g. a thumbnail in a dialog over the page, came up as a broken image.)
 */
const shared = new Map<Blob, { url: string; users: number; timer?: ReturnType<typeof setTimeout> }>()

function objectUrl(blob: Blob) {
  let entry = shared.get(blob)
  if (!entry) {
    entry = { url: URL.createObjectURL(blob), users: 0 }
    shared.set(blob, entry)
  }
  return entry.url
}

/** An object URL for a file served by the API (which needs the user's token, so <img src> can't load it). */
export function useAuthedBlobUrl(path: string | null | undefined) {
  const { data } = useQuery({
    queryKey: ['blob', path],
    queryFn: async () => (await api.get<Blob>(path!, { responseType: 'blob' })).data,
    enabled: !!path,
    staleTime: Infinity,
    gcTime: 5 * 60_000,
  })
  useEffect(() => {
    if (!data) return
    objectUrl(data)
    const entry = shared.get(data)!
    entry.users += 1
    clearTimeout(entry.timer)
    return () => {
      entry.users -= 1
      if (entry.users === 0) {
        entry.timer = setTimeout(() => {
          if (entry.users === 0) {
            URL.revokeObjectURL(entry.url)
            shared.delete(data)
          }
        }, 1000)
      }
    }
  }, [data])
  return data ? objectUrl(data) : null
}
