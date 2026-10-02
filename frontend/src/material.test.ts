import { describe, expect, it } from 'vitest'
import { capturedMaterial } from './material'

describe('capturedMaterial', () => {
  it('has no captures in starting position', () => {
    const result = capturedMaterial('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')
    expect(result).toEqual({ byWhite: [], byBlack: [], whiteGain: 0, blackGain: 0, balance: 0 })
  })

  it('counts missing black queen and white rook', () => {
    const result = capturedMaterial('rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/1NBQKBNR w Kkq - 0 1')
    expect(result.byWhite).toEqual(['q'])
    expect(result.byBlack).toEqual(['R'])
    expect(result.whiteGain).toBe(9)
    expect(result.blackGain).toBe(5)
    expect(result.balance).toBe(4)
  })
})
