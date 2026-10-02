export interface CapturedMaterial {
  byWhite: string[]
  byBlack: string[]
  whiteGain: number
  blackGain: number
  balance: number
}

const INITIAL_COUNTS: Record<string, number> = {
  P: 8, N: 2, B: 2, R: 2, Q: 1,
  p: 8, n: 2, b: 2, r: 2, q: 1,
}

const VALUES: Record<string, number> = {
  P: 1, N: 3, B: 3, R: 5, Q: 9,
  p: 1, n: 3, b: 3, r: 5, q: 9,
}

const ORDER = ['Q', 'R', 'B', 'N', 'P', 'q', 'r', 'b', 'n', 'p']

export function capturedMaterial(fen: string): CapturedMaterial {
  const board = fen.split(' ')[0]
  const current: Record<string, number> = {}
  for (const token of board) {
    if (/[prnbqPRNBQ]/.test(token)) current[token] = (current[token] ?? 0) + 1
  }
  const captured: string[] = []
  for (const piece of ORDER) {
    const missing = Math.max(0, (INITIAL_COUNTS[piece] ?? 0) - (current[piece] ?? 0))
    captured.push(...Array(missing).fill(piece))
  }
  const byWhite = captured.filter((piece) => piece === piece.toLowerCase())
  const byBlack = captured.filter((piece) => piece === piece.toUpperCase())
  const whiteGain = byWhite.reduce((sum, piece) => sum + VALUES[piece], 0)
  const blackGain = byBlack.reduce((sum, piece) => sum + VALUES[piece], 0)
  return { byWhite, byBlack, whiteGain, blackGain, balance: whiteGain - blackGain }
}
