import { capturedMaterial } from './material'

const GLYPHS: Record<string, string> = {
  P: '♟', N: '♞', B: '♝', R: '♜', Q: '♛',
  p: '♟', n: '♞', b: '♝', r: '♜', q: '♛',
}

interface Props {
  fen: string
  side: 'white' | 'black'
}

export function MaterialBar({ fen, side }: Props) {
  const material = capturedMaterial(fen)
  const pieces = side === 'white' ? material.byWhite : material.byBlack
  const gain = side === 'white' ? material.whiteGain : material.blackGain
  const advantage = side === 'white' ? material.balance : -material.balance
  return (
    <div className={`material-bar material-${side}`} aria-label={`${side === 'white' ? 'Белые' : 'Чёрные'} взяли материала на ${gain}`}>
      <span className="material-label">{side === 'white' ? 'Белые взяли' : 'Чёрные взяли'}</span>
      <span className="captured-pieces">{pieces.length ? pieces.map((piece, index) => <span key={`${piece}-${index}`}>{GLYPHS[piece]}</span>) : <i>—</i>}</span>
      <strong>{gain > 0 ? `+${gain}` : '0'}</strong>
      {advantage > 0 && <em>перевес +{advantage}</em>}
    </div>
  )
}
