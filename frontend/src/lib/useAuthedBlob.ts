import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo } from 'react'
import { api } from './api'

/** An object URL for a file served by the API (which needs the user's token, so <img src> can't load it). */
export function useAuthedBlobUrl(path: string | null | undefined) {
  const { data } = useQuery({
    queryKey: ['blob', path],
    queryFn: async () => (await api.get<Blob>(path!, { responseType: 'blob' })).data,
    enabled: !!path,
    staleTime: Infinity,
    gcTime: 5 * 60_000,
  })
  const url = useMemo(() => (data ? URL.createObjectURL(data) : null), [data])
  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url)
  }, [url])
  return url
}
