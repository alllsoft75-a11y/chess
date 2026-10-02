export function isPromotionMove(fen: string, from: string, to: string): boolean {
  const board = fen.split(' ')[0]
  const file = from.charCodeAt(0) - 97
  const rank = 8 - Number(from[1])
  let currentFile = 0
  let piece: string | undefined
  for (const token of board.split('/')[rank] ?? '') {
    if (/\d/.test(token)) {
      currentFile += Number(token)
    } else {
      if (currentFile === file) piece = token
      currentFile += 1
    }
  }
  if (piece !== 'P' && piece !== 'p') return false
  const destinationRank = Number(to[1])
  return destinationRank === 1 || destinationRank === 8
}
