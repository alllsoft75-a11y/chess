import type { CSSProperties } from 'react'
import type { Motif, PieceAssessment, SquareControl } from './types'

export type ControlLayer = 'off' | 'white' | 'black' | 'balance' | 'tension'

const PIECES: Record<string, string> = {
  K: '♚', Q: '♛', R: '♜', B: '♝', N: '♞', P: '♟',
  k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟',
}

function parseBoard(fen: string): (string | null)[][] {
  return fen.split(' ')[0].split('/').map((rank) => {
    const squares: (string | null)[] = []
    for (const value of rank) {
      if (/\d/.test(value)) {
        squares.push(...Array(Number(value)).fill(null))
      } else {
        squares.push(value)
      }
    }
    return squares
  })
}

interface Props {
  fen: string
  lastMove: string | null
  flipped: boolean
  assessments: PieceAssessment[]
  controls: SquareControl[]
  controlLayer: ControlLayer
  showActivity: boolean
  motifs: Motif[]
  selectedMotif: number | null
  selectedSquare: string | null
  onSelect: (square: string) => void
}

function controlStyle(control: SquareControl | undefined, layer: ControlLayer): CSSProperties | undefined {
  if (!control || layer === 'off') return undefined
  if (layer === 'white') {
    const alpha = Math.min(0.62, control.white_effective.length * 0.16)
    return { '--control-color': `rgba(72, 136, 224, ${alpha})` } as CSSProperties
  }
  if (layer === 'black') {
    const alpha = Math.min(0.62, control.black_effective.length * 0.16)
    return { '--control-color': `rgba(220, 74, 67, ${alpha})` } as CSSProperties
  }
  if (layer === 'tension') {
    const alpha = Math.min(0.68, control.tension * 0.22)
    return { '--control-color': `rgba(224, 153, 42, ${alpha})` } as CSSProperties
  }
  const intensity = Math.min(0.62, Math.abs(control.balance) * 0.16)
  const color = control.balance >= 0 ? `rgba(72, 136, 224, ${intensity})` : `rgba(220, 74, 67, ${intensity})`
  return { '--control-color': color } as CSSProperties
}

export function ChessBoard({ fen, lastMove, flipped, assessments, controls, controlLayer, showActivity, motifs, selectedMotif, selectedSquare, onSelect }: Props) {
  const board = parseBoard(fen)
  const ranks = flipped ? [...board].reverse() : board
  const files = flipped ? [...Array(8).keys()].reverse() : [...Array(8).keys()]
  const lastSquares = lastMove ? [lastMove.slice(0, 2), lastMove.slice(2, 4)] : []
  const assessmentBySquare = new Map(assessments.map((item) => [item.square, item]))
  const controlBySquare = new Map(controls.map((item) => [item.square, item]))
  const motif = selectedMotif === null ? null : motifs[selectedMotif]
  const motifSquares = new Set(motif ? [motif.actor, ...motif.targets, ...motif.line, ...(motif.blocker ? [motif.blocker] : [])] : [])

  return (
    <div className="board" aria-label="Шахматная доска">
      {ranks.flatMap((rank, visualRank) => files.map((file, visualFile) => {
        const sourceRank = flipped ? 7 - visualRank : visualRank
        const square = `${String.fromCharCode(97 + file)}${8 - sourceRank}`
        const piece = rank[file]
        const dark = (sourceRank + file) % 2 === 1
        return (
          <button
            className={`square ${dark ? 'dark' : 'light'} ${lastSquares.includes(square) ? 'last' : ''} ${selectedSquare === square ? 'selected' : ''} ${motifSquares.has(square) ? 'motif-square' : ''} ${motif?.blocker === square ? 'motif-blocker' : ''}`}
            key={square}
            title={assessmentBySquare.get(square)?.explanation ?? controlBySquare.get(square)?.explanation ?? square}
            onClick={() => onSelect(square)}
            style={controlStyle(controlBySquare.get(square), controlLayer)}
          >
            {controlLayer !== 'off' && <span className="control-overlay" />}
            {visualFile === 0 && <span className="rank-label">{8 - sourceRank}</span>}
            {visualRank === 7 && <span className="file-label">{String.fromCharCode(97 + file)}</span>}
            {piece && showActivity && assessmentBySquare.has(square) && (
              <span
                className={`activity-halo activity-${assessmentBySquare.get(square)!.activity.state.toLowerCase()}`}
                style={{ '--activity-scale': `${0.7 + assessmentBySquare.get(square)!.activity.index / 250}` } as CSSProperties}
              />
            )}
            {piece && <span className={`piece ${piece === piece.toUpperCase() ? 'piece-white' : 'piece-black'}`}>{PIECES[piece]}</span>}
            {piece && assessmentBySquare.has(square) && (
              <span className={`vulnerability vulnerability-${assessmentBySquare.get(square)!.state.toLowerCase()}`} aria-label={assessmentBySquare.get(square)!.state} />
            )}
          </button>
        )
      }))}
    </div>
  )
}