import { useEffect, useState } from 'react'
import { ChessBoard } from './ChessBoard'
import { MaterialBar } from './MaterialBar'
import { CharacterAvatar } from './CharacterAvatar'
import { isPromotionMove } from './promotion'
import type { MoveCandidate, PersonalityProfile, PositionAnalysis } from './types'

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

const PROMOTION_PIECES = [
  { code: 'q', label: 'Ферзь', glyph: '♛' },
  { code: 'r', label: 'Ладья', glyph: '♜' },
  { code: 'b', label: 'Слон', glyph: '♝' },
  { code: 'n', label: 'Конь', glyph: '♞' },
] as const

interface Props {
  onReview: (pgn: string) => void
}

export function PlayGame({ onReview }: Props) {
  const [fen, setFen] = useState(START_FEN)
  const [personalities, setPersonalities] = useState<PersonalityProfile[]>([])
  const [personalityId, setPersonalityId] = useState('universal')
  const [gameId, setGameId] = useState<number | null>(null)
  const [serverPgn, setServerPgn] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<PositionAnalysis | null>(null)
  const [source, setSource] = useState<string | null>(null)
  const [moves, setMoves] = useState<{ player: MoveCandidate; program: MoveCandidate | null }[]>([])
  const [message, setMessage] = useState('Вы играете белыми. Выберите фигуру и поле назначения.')
  const [speech, setSpeech] = useState<string | null>(null)
  const [thinking, setThinking] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [emotion, setEmotion] = useState<string | null>(null)
  const [pendingPromotion, setPendingPromotion] = useState<{ from: string; to: string } | null>(null)

  useEffect(() => {
    fetch('/api/v1/personalities').then((response) => response.json()).then(setPersonalities).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (gameId !== null) return
    fetch('/api/v1/saved-games', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ player_name: 'Player', player_color: 'white', personality_id: personalityId }),
    }).then((response) => response.json()).then((payload) => {
      setGameId(payload.id)
      setFen(payload.fen)
      setServerPgn(payload.pgn)
    }).catch(() => setMessage('Не удалось создать серверную игровую сессию.'))
  }, [gameId, personalityId])

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/v1/positions/analyze', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fen }), signal: controller.signal,
    }).then((response) => response.json()).then(setAnalysis).catch(() => undefined)
    return () => controller.abort()
  }, [fen])

  async function selectSquare(square: string) {
    if (thinking || result || gameId === null) return
    if (!source) {
      setSource(square)
      setMessage(`Выбрано ${square}. Укажите поле назначения.`)
      return
    }
    if (isPromotionMove(fen, source, square)) {
      setPendingPromotion({ from: source, to: square })
      setSource(null)
      setMessage('Пешка достигает последней горизонтали. Выберите фигуру превращения.')
      return
    }
    await submitMove(`${source}${square}`)
  }

  async function submitMove(move: string) {
    if (gameId === null) return
    setThinking(true)
    try {
      const playerResponse = await fetch(`/api/v1/saved-games/${gameId}/player-move`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ move }),
      })
      const playerPayload = await playerResponse.json()
      if (!playerResponse.ok) throw new Error(playerPayload.detail ?? 'Ход отклонён')
      setFen(playerPayload.fen)
      setServerPgn(playerPayload.pgn)
      setMoves((items) => [...items, { player: playerPayload.player_move, program: null }])
      setMessage(`Вы сыграли ${playerPayload.player_move.san}. Программа размышляет…`)
      await new Promise<void>((resolve) => window.requestAnimationFrame(() => window.requestAnimationFrame(() => resolve())))
      const playerFinished = playerPayload.status === 'finished' && playerPayload.result !== '*'
      if (playerFinished) {
        setResult(playerPayload.result)
        setMessage(`Партия окончена: ${playerPayload.result}.`)
        return
      }
      const programResponse = await fetch(`/api/v1/saved-games/${gameId}/program-move`, { method: 'POST' })
      const programPayload = await programResponse.json()
      if (!programResponse.ok) throw new Error(programPayload.detail ?? 'Программа не смогла ответить')
      setFen(programPayload.fen)
      setServerPgn(programPayload.pgn)
      setMoves((items) => items.map((item, itemIndex) => itemIndex === items.length - 1 ? { ...item, program: programPayload.program_move } : item))
      const finishedResult = programPayload.status === 'finished' && programPayload.result !== '*' ? programPayload.result : null
      setResult(finishedResult)
      setEmotion(programPayload.emotion ?? null)
      setSpeech(programPayload.utterance || null)
      setMessage(programPayload.program_move
        ? `Программа ответила ${programPayload.program_move.san}. План: ${programPayload.program_move.plan}. Ожидаемый ответ: ${programPayload.program_move.expected_reply ?? 'не определён'}${programPayload.program_move.continuation ? `; продолжение: ${programPayload.program_move.continuation}` : ''}. ${programPayload.program_move.reasons.join('; ')}.`
        : programPayload.resignation_reason
          ? `Программа сдалась: ${programPayload.resignation_reason}.`
          : finishedResult ? `Партия окончена: ${finishedResult}.` : 'Ваш ход.')
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSource(null)
      setPendingPromotion(null)
      setThinking(false)
    }
  }

  function pgn(): string {
    const notation = moves.map((turn, index) => `${index + 1}. ${turn.player.san}${turn.program ? ` ${turn.program.san}` : ''}`).join(' ')
    return `[Event "Chess Vision friendly game"]\n[White "Player"]\n[Black "Chess Vision"]\n[Result "${result ?? '*'}"]\n\n${notation} ${result ?? '*'}`
  }

  function download() {
    const link = document.createElement('a')
    link.href = URL.createObjectURL(new Blob([serverPgn ?? pgn()], { type: 'application/x-chess-pgn' }))
    link.download = 'chess-vision-game.pgn'
    link.click()
    URL.revokeObjectURL(link.href)
  }

  return (
    <section className="play-workspace">
      <div className="board-column">
        <MaterialBar fen={fen} side="black" />
        <ChessBoard
          fen={fen}
          lastMove={moves.at(-1)?.program?.uci ?? moves.at(-1)?.player.uci ?? null}
          flipped={false}
          assessments={analysis?.pieces ?? []}
          controls={analysis?.squares ?? []}
          controlLayer="off"
          showActivity
          motifs={analysis?.motifs ?? []}
          selectedMotif={null}
          selectedSquare={source}
          onSelect={(square) => void selectSquare(square)}
        />
        <MaterialBar fen={fen} side="white" />
      </div>
      <aside className="play-panel">
        <div className="console-label">ИГРОК ПРОТИВ ПЕРСОНАЖА</div>
        <label className="personality-picker">
          Персонаж
          <select value={personalityId} disabled={moves.length > 0 || thinking} onChange={(event) => {
            setPersonalityId(event.target.value)
            setGameId(null)
            setMoves([])
            setFen(START_FEN)
            setServerPgn(null)
            setSpeech(null)
            setEmotion(null)
          }}>
            {personalities.map((personality) => <option value={personality.id} key={personality.id}>{personality.name} — {personality.temperament}</option>)}
          </select>
        </label>
        <p className="personality-description">{personalities.find((item) => item.id === personalityId)?.description}</p>
        <div className="character-presentation">
          <div className="character-speech-bubble">
            <div className="speech-header">
              <span className="speech-author">{personalities.find((item) => item.id === personalityId)?.name ?? 'Персонаж'}</span>
              {emotion && <span className={`emotion emotion-${emotion}`}>{emotion}</span>}
            </div>
            <p className={`speech-quote${speech ? '' : ' speech-silent'}`}>
              {thinking ? '…' : speech ? `«${speech}»` : '…'}
            </p>
          </div>
          <CharacterAvatar
            personality={personalities.find((item) => item.id === personalityId)}
            emotion={emotion}
            thinking={thinking}
            result={result}
          />
        </div>
        <p className="character-speech">{thinking ? 'Персонаж выбирает ход…' : message}</p>
        {pendingPromotion && (
          <div className="promotion-picker" role="dialog" aria-label="Выбор фигуры превращения">
            <span>Превращение пешки на {pendingPromotion.to}</span>
            <div className="promotion-options">
              {PROMOTION_PIECES.map((piece) => (
                <button key={piece.code} onClick={() => void submitMove(`${pendingPromotion.from}${pendingPromotion.to}${piece.code}`)}>
                  <span className="promotion-glyph">{piece.glyph}</span>
                  {piece.label}
                </button>
              ))}
              <button className="promotion-cancel" onClick={() => { setPendingPromotion(null); setMessage('Превращение отменено. Выберите ход.') }}>Отмена</button>
            </div>
          </div>
        )}
        <div className="play-notation">
          {moves.map((turn, index) => <div key={index}><span>{index + 1}.</span><b>{turn.player.san}</b><b>{turn.program?.san ?? ''}</b></div>)}
        </div>
        <article className="situation-summary">
          <strong>{analysis?.situation.context ?? 'POSITION'}</strong>
          <p>{analysis?.situation.headline}</p>
        </article>
        <div className="play-actions">
          <button onClick={() => { setGameId(null); setFen(START_FEN); setServerPgn(null); setMoves([]); setResult(null); setSource(null); setPendingPromotion(null); setSpeech(null); setEmotion(null); setMessage('Новая партия. Вы играете белыми.') }}>Новая партия</button>
          <button disabled={!moves.length} onClick={download}>Сохранить PGN</button>
          <button disabled={!moves.length} onClick={() => onReview(serverPgn ?? pgn())}>Дружеский разбор</button>
        </div>
      </aside>
    </section>
  )
}