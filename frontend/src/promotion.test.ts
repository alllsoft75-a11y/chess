import { describe, expect, it } from 'vitest'
import { isPromotionMove } from './promotion'

describe('isPromotionMove', () => {
  const whitePawnE7 = '4k3/4P3/8/8/8/8/8/4K3 w - - 0 1'
  const blackPawnE2 = '4k3/8/8/8/8/8/4p3/4K3 b - - 0 1'
  const knightNearLastRank = 'N3k3/8/8/8/8/8/8/4K3 w - - 0 1'
  const whitePawnMiddle = '4k3/8/8/4P3/8/8/8/4K3 w - - 0 1'

  it('detects white pawn reaching eighth rank', () => {
    expect(isPromotionMove(whitePawnE7, 'e7', 'e8')).toBe(true)
  })

  it('detects black pawn reaching first rank', () => {
    expect(isPromotionMove(blackPawnE2, 'e2', 'e1')).toBe(true)
  })

  it('ignores knight moving to last rank', () => {
    expect(isPromotionMove(knightNearLastRank, 'a8', 'b6')).toBe(false)
  })

  it('ignores pawn not reaching last rank', () => {
    expect(isPromotionMove(whitePawnMiddle, 'e5', 'e6')).toBe(false)
  })
})
