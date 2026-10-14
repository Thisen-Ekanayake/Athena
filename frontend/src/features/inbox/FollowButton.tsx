import { BellPlus, BellRing } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { targetKey, useFollow, useUnfollow, useWatches, type FollowTarget } from '../../api/queries/inbox'
import { Button } from '../../ui/Button'
import { cn } from '../../ui/cn'

const WHAT: Record<FollowTarget['kind'], string> = {
  map: 'Updates to this map, and new papers citing its milestones, come to your inbox',
  search: 'New feed items that match this search come to your inbox',
  source: 'New items from this source come to your inbox',
  cluster: 'New items in this cluster come to your inbox',
}

/** Follow or stop following a map, search, source or cluster. Settings → Notifications says how news arrives. */
export function FollowButton({ target, className }: { target: FollowTarget; className?: string }) {
  const watches = useWatches()
  const follow = useFollow()
  const unfollow = useUnfollow()
  const watch = watches.data?.watches.find((w) => w.target === targetKey(target))
  const busy = follow.isPending || unfollow.isPending
  const error = follow.error ?? unfollow.error

  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <Button
        variant="secondary"
        size="sm"
        disabled={busy || watches.isLoading}
        aria-pressed={!!watch}
        title={watch ? `Following${watch.delivery === 'digest' ? ' (in your digest)' : ''}. Click to stop following.` : WHAT[target.kind]}
        onClick={() => (watch ? unfollow.mutate(watch.id) : follow.mutate(target))}
        className={cn(watch && 'border-accent-line [&_svg]:text-accent')}
      >
        {watch ? <BellRing /> : <BellPlus />}
        {watch ? 'Following' : 'Follow'}
      </Button>
      {error && <span role="alert" className="text-[12px] text-bad">{apiErrorMessage(error, 'Could not change this follow')}</span>}
    </span>
  )
}
