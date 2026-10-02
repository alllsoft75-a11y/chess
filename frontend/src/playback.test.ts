import { describe, expect, it } from 'vitest'
import { hasTempo, playbackDelay } from './playback'
import type { TimelineNode } from './types'

const node = (elapsed: number | null): TimelineNode => ({
  ply: 1,
  move_number: 1,
  side: 'white',
  san: 'e4',
  uci: 'e2e4',
  fen: '',
  clock_seconds: null,
  elapsed_seconds: elapsed,
  elapsed_is_estimated: false,
  comment: null,
})

describe('playback timing', () => {
  it('uses tempo and speed', () => {
    expect(playbackDelay(node(4), 'tempo', 1, 2)).toBe(2000)
  })

  it('falls back to fixed and clamps delay', () => {
    expect(playbackDelay(node(null), 'tempo', 0.1, 1)).toBe(250)
  })

  it('detects available timing', () => {
    expect(hasTempo([node(null), node(3)])).toBe(true)
  })
})
