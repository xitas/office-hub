import { Badge } from '@/components/ui/badge'

export function TagList({ tags, max = 3 }: { tags: string[]; max?: number }) {
  if (!tags.length) return null
  return (
    <div className="flex flex-wrap gap-1">
      {tags.slice(0, max).map((tag) => (
        <Badge key={tag} variant="secondary" className="font-normal">
          {tag}
        </Badge>
      ))}
      {tags.length > max && (
        <Badge variant="outline" className="font-normal">
          +{tags.length - max}
        </Badge>
      )}
    </div>
  )
}
