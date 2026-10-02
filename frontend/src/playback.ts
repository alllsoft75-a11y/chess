import type { PlaybackMode, TimelineNode } from './types'

export function playbackDelay(
  node: TimelineNode,
  mode: PlaybackMode,
  fixedSeconds: number,
  speed: number,
): number {
  const source = mode === 'tempo' ? node.elapsed_seconds ?? fixedSeconds : fixedSeconds
  return Math.min(10_000, Math.max(250, (source * 1000) / speed))
}

export function hasTempo(timeline: TimelineNode[]): boolean {
  return timeline.slice(1).some((node) => node.elapsed_seconds !== null)
}
