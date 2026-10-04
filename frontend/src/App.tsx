import { useEffect, useMemo, useRef, useState } from 'react'
import { ChessBoard } from './ChessBoard'
import type { ControlLayer } from './ChessBoard'
import { hasTempo, playbackDelay } from './playback'
import { PlayGame } from './PlayGame'
import { TournamentPage } from './TournamentPage'
import { MaterialBar } from './MaterialBar'
import type { EpisodeAnalysis, MoveAnalysis, ParsedGame, PlaybackMode, PositionAnalysis } from './types'

function formatClock(seconds: number | null): string {
  if (seconds === null) return '—'
  const minutes = Math.floor(seconds / 60)
  const rest = Math.floor(seconds % 60)
  return `${minutes}:${rest.toString().padStart(2, '0')}`
}

export function App() {
  const [game, setGame] = useState<ParsedGame | null>(null)
  const [screen, setScreen] = useState<'review' | 'play' | 'tournament'>('review')
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [mode, setMode] = useState<PlaybackMode>('fixed')
  const [fixedSeconds, setFixedSeconds] = useState(1)
  const [speed, setSpeed] = useState(1)
  const [flipped, setFlipped] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<PositionAnalysis | null>(null)
  const [moveAnalysis, setMoveAnalysis] = useState<MoveAnalysis | null>(null)
  const [episodeAnalysis, setEpisodeAnalysis] = useState<EpisodeAnalysis | null>(null)
  const [selectedSquare, setSelectedSquare] = useState<string | null>(null)
  const [controlLayer, setControlLayer] = useState<ControlLayer>('off')
  const [showActivity, setShowActivity] = useState(true)
  const [selectedMotif, setSelectedMotif] = useState<number | null>(null)
  const notationRef = useRef<HTMLDivElement>(null)

  const current = game?.timeline[index] ?? null
  const tempoAvailable = game ? hasTempo(game.timeline) : false

  useEffect(() => {
    if (!playing || !game || index >= game.timeline.length - 1) return
    const next = game.timeline[index + 1]
    const timer = window.setTimeout(() => {
      const updated = Math.min(index + 1, game.timeline.length - 1)
      setIndex(updated)
      if (updated === game.timeline.length - 1) setPlaying(false)
    }, playbackDelay(next, mode, fixedSeconds, speed))
    return () => window.clearTimeout(timer)
  }, [fixedSeconds, game, index, mode, playing, speed])

  useEffect(() => {
    notationRef.current?.querySelector(`[data-ply="${index}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [index])

  useEffect(() => {
    if (!current || !game) return
    const controller = new AbortController()
    const previous = index > 0 ? game.timeline[index - 1] : null
    const endpoint = previous && current.uci ? '/api/v1/moves/analyze' : '/api/v1/positions/analyze'
    const body = previous && current.uci ? { fen: previous.fen, move: current.uci } : { fen: current.fen }
    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = await response.json()
        if (!response.ok) throw new Error(payload.detail ?? 'Не удалось оценить позицию')
        if ('events' in payload) {
          setMoveAnalysis(payload)
          setAnalysis(payload.after)
        } else {
          setMoveAnalysis(null)
          setAnalysis(payload)
        }
      })
      .catch((reason) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return
        setError(reason instanceof Error ? reason.message : String(reason))
      })
    return () => controller.abort()
  }, [current, game, index])

  useEffect(() => {
    if (!game || index < 2) return
    const first = game.timeline[index - 1]
    const second = game.timeline[index]
    const start = game.timeline[index - 2]
    if (!first.uci || !second.uci) return
    const controller = new AbortController()
    const requestEpisode = async (fen: string, firstMove: string, secondMove: string) => {
      const response = await fetch('/api/v1/episodes/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fen, first_move: firstMove, second_move: secondMove }),
        signal: controller.signal,
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail ?? 'Не удалось оценить эпизод')
      return payload as EpisodeAnalysis
    }
    const currentEpisode = requestEpisode(start.fen, first.uci, second.uci)
    const precedingEpisode = index >= 3 && game.timeline[index - 2].uci && game.timeline[index - 1].uci
      ? requestEpisode(game.timeline[index - 3].fen, game.timeline[index - 2].uci!, game.timeline[index - 1].uci!)
      : Promise.resolve(null)
    Promise.all([currentEpisode, precedingEpisode])
      .then(([currentResult, precedingResult]) => {
        const completedKinds = new Set(['EQUAL_EXCHANGE', 'FAVORABLE_EXCHANGE', 'UNFAVORABLE_EXCHANGE'])
        setEpisodeAnalysis(precedingResult && completedKinds.has(precedingResult.kind) ? precedingResult : currentResult)
      })
      .catch((reason) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return
        setError(reason instanceof Error ? reason.message : String(reason))
      })
    return () => controller.abort()
  }, [game, index])

  const activeCaptureChain = game?.capture_chains.find((chain) => index >= chain.start_ply && index <= chain.end_ply + 1) ?? null
  const selectedAssessment = analysis?.pieces.find((piece) => piece.square === selectedSquare) ?? null
  const selectedControl = analysis?.squares.find((square) => square.square === selectedSquare) ?? null

  const clocks = useMemo(() => {
    if (!game) return { white: null, black: null }
    let white: number | null = null
    let black: number | null = null
    for (let i = 1; i <= index; i += 1) {
      const node = game.timeline[i]
      if (node.side === 'white' && node.clock_seconds !== null) white = node.clock_seconds
      if (node.side === 'black' && node.clock_seconds !== null) black = node.clock_seconds
    }
    return { white, black }
  }, [game, index])

  async function parsePgn(pgn: string) {
    setError(null)
    setPlaying(false)
    const response = await fetch('/api/v1/games/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pgn }),
    })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.detail ?? 'Не удалось загрузить PGN')
    setGame(payload)
    setScreen('review')
    setIndex(0)
    setMode(hasTempo(payload.timeline) ? 'tempo' : 'fixed')
  }

  async function loadFile(file: File) {
    try {
      await parsePgn(await file.text())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    }
  }

  function jump(next: number) {
    setPlaying(false)
    setSelectedSquare(null)
    setEpisodeAnalysis(null)
    setSelectedMotif(null)
    if (game) setIndex(Math.max(0, Math.min(next, game.timeline.length - 1)))
  }

  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">CHESS VISION / PGN PLAYER</p>
          <h1>Воспроизведение партии</h1>
        </div>
        <div className="header-actions">
          <button className={screen === 'play' ? 'active' : ''} onClick={() => setScreen('play')}>Играть</button>
          <button className={screen === 'tournament' ? 'active' : ''} onClick={() => setScreen('tournament')}>Турниры</button>
          <label className="file-button">
            Загрузить PGN
            <input type="file" accept=".pgn,text/plain" onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void loadFile(file)
            }} />
          </label>
        </div>
      </header>

      {screen === 'play' ? (
        <PlayGame onReview={(pgn) => void parsePgn(pgn)} />
      ) : screen === 'tournament' ? (
        <TournamentPage onReview={(pgn) => void parsePgn(pgn)} />
      ) : !game ? (
        <section className="empty-state">
          <div className="drop-card">
            <h2>Откройте PGN-файл</h2>
            <p>Доска, нотация и часы будут синхронизированы с каждым полуходом.</p>
            <label className="file-button">
              Выбрать файл
              <input type="file" accept=".pgn,text/plain" onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void loadFile(file)
              }} />
            </label>
            {error && <p className="error">{error}</p>}
          </div>
        </section>
      ) : (
        <>
          <section className="game-summary">
            <div><strong>{game.headers.white ?? 'Белые'}</strong><span>{game.headers.white_elo ?? '—'}</span></div>
            <div className="result">{game.headers.result}<small>{game.headers.opening}</small></div>
            <div><strong>{game.headers.black ?? 'Чёрные'}</strong><span>{game.headers.black_elo ?? '—'}</span></div>
          </section>

          <section className="workspace">
            <div className="board-column">
              <div className="clock-row"><span>Чёрные</span><strong>{formatClock(clocks.black)}</strong></div>
              <MaterialBar fen={current!.fen} side="black" />
              <ChessBoard
                fen={current!.fen}
                lastMove={current!.uci}
                flipped={flipped}
                assessments={analysis?.pieces ?? []}
                controls={analysis?.squares ?? []}
                controlLayer={controlLayer}
                showActivity={showActivity}
                motifs={analysis?.motifs ?? []}
                selectedMotif={selectedMotif}
                selectedSquare={selectedSquare}
                onSelect={setSelectedSquare}
              />
              <MaterialBar fen={current!.fen} side="white" />
              <div className="clock-row"><span>Белые</span><strong>{formatClock(clocks.white)}</strong></div>
            </div>

            <aside className="side-panel">
              <div className="panel-title"><span>Партия</span><button onClick={() => setFlipped((value) => !value)}>Перевернуть</button></div>
              <div className="layer-controls">
                <span>Контроль полей</span>
                {(['off', 'white', 'black', 'balance', 'tension'] as ControlLayer[]).map((layer) => (
                  <button className={controlLayer === layer ? 'active' : ''} key={layer} onClick={() => setControlLayer(layer)}>
                    {{ off: 'Выкл', white: 'Белые', black: 'Чёрные', balance: 'Баланс', tension: 'Напряжение' }[layer]}
                  </button>
                ))}
                <button className={showActivity ? 'active' : ''} onClick={() => setShowActivity((value) => !value)}>Активность</button>
              </div>
              <div className="notation" ref={notationRef}>
                {game.timeline.slice(1).map((node) => (
                  <button
                    className={node.ply === index ? 'active' : ''}
                    data-ply={node.ply}
                    key={node.ply}
                    onClick={() => jump(node.ply)}
                  >
                    <span>{node.side === 'white' ? `${node.move_number}.` : `${node.move_number}...`}</span>
                    <strong>{node.san}</strong>
                    <small>{formatClock(node.clock_seconds)}</small>
                  </button>
                ))}
              </div>
              <div className="reasoning-console">
                <div className="console-label">ТЕКСТОВАЯ КОНСОЛЬ</div>
                <div className="console-section-title context-title">КОНТЕКСТ ХОДА</div>
                {index === 0 ? <p>Начальная позиция.</p> : activeCaptureChain ? (
                  <article className={`episode episode-${activeCaptureChain.kind.toLowerCase()}`}>
                    <strong>{activeCaptureChain.headline}</strong>
                    <p>{activeCaptureChain.events.map((event) => event.san).join(' → ')}</p>
                    <p>{activeCaptureChain.message}</p>
                  </article>
                ) : episodeAnalysis && (
                  <article className={`episode episode-${episodeAnalysis.kind.toLowerCase()}`}>
                    <strong>{episodeAnalysis.headline}</strong>
                    <p>{episodeAnalysis.message}</p>
                  </article>
                )}
                {current!.elapsed_seconds !== null && (
                  <p>Время на ход: {current!.elapsed_seconds.toFixed(1)} с{current!.elapsed_is_estimated ? ' (расчёт по часам)' : ''}.</p>
                )}
                {moveAnalysis?.changes.length ? (
                  <section className="transition-events">
                    <div className="console-section-title">СМЫСЛ ХОДА</div>
                    {moveAnalysis.changes.slice(0, 4).map((change, changeIndex) => (
                      <button className={`observation situation-${change.impact}`} key={`${change.category}-${changeIndex}`} onClick={() => {
                        setSelectedSquare(change.subjects[0] ?? null)
                        setSelectedMotif(null)
                      }}>
                        <strong>{change.headline}</strong>
                        <span>{change.message}</span>
                      </button>
                    ))}
                    <details className="technical-events">
                      <summary>Технические события ({moveAnalysis.events.length})</summary>
                      {moveAnalysis.events.slice(0, 8).map((event, eventIndex) => (
                        <button className={`observation transition-${event.severity}`} key={`${event.code}-${eventIndex}`} onClick={() => setSelectedSquare(event.subjects[0] ?? null)}>
                          <strong>{event.code}</strong>
                          <span>{event.message}</span>
                        </button>
                      ))}
                    </details>
                  </section>
                ) : index > 0 ? <p>Значимых ситуационных изменений не обнаружено.</p> : null}
                <div className="console-section-title">СИТУАЦИЯ</div>
                {analysis?.situation && (
                  <article className="situation-summary">
                    <strong>{analysis.situation.context}</strong>
                    <p>{analysis.situation.headline}</p>
                    <div className="situation-sides">
                      <div><b>Белые</b><span>{analysis.situation.white.posture}</span><small>Атака: {analysis.situation.white.attack} · Защита: {analysis.situation.white.defense} · Координация: {analysis.situation.white.coordination}</small></div>
                      <div><b>Чёрные</b><span>{analysis.situation.black.posture}</span><small>Атака: {analysis.situation.black.attack} · Защита: {analysis.situation.black.defense} · Координация: {analysis.situation.black.coordination}</small></div>
                    </div>
                  </article>
                )}
                <div className="console-section-title">ТЕКУЩАЯ ПОЗИЦИЯ</div>
                {selectedAssessment ? (
                  <article className={`observation observation-${selectedAssessment.state.toLowerCase()}`}>
                    <strong>{selectedAssessment.state} · {selectedAssessment.square}</strong>
                    <p>{selectedAssessment.explanation}</p>
                    <small>Атакующие: {selectedAssessment.legal_attackers.join(', ') || 'нет'} · Защитники: {selectedAssessment.defenders.join(', ') || 'нет'} · Безопасные отходы: {selectedAssessment.safe_moves.join(', ') || 'нет'}</small>
                    <strong className="activity-title">АКТИВНОСТЬ · {selectedAssessment.activity.state} · {selectedAssessment.activity.index}/100</strong>
                    <p>{selectedAssessment.activity.explanation}</p>
                    <small>Легальные поля: {selectedAssessment.activity.legal_moves.join(', ') || 'нет'} · Безопасные: {selectedAssessment.activity.safe_moves.join(', ') || 'нет'} · Взятия: {selectedAssessment.activity.captures.join(', ') || 'нет'}</small>
                    {selectedControl && <small>{selectedControl.explanation} Белые: {selectedControl.white_effective.join(', ') || 'нет'} · Чёрные: {selectedControl.black_effective.join(', ') || 'нет'}</small>}
                  </article>
                ) : selectedControl ? (
                  <article className="observation">
                    <strong>КОНТРОЛЬ · {selectedControl.square}</strong>
                    <p>{selectedControl.explanation}</p>
                    <small>Белые: {selectedControl.white_effective.join(', ') || 'нет'} · Чёрные: {selectedControl.black_effective.join(', ') || 'нет'} · Пешечный контроль: {selectedControl.white_pawn_control ? 'белые ' : ''}{selectedControl.black_pawn_control ? 'чёрные' : ''}{!selectedControl.white_pawn_control && !selectedControl.black_pawn_control ? 'нет' : ''}</small>
                  </article>
                ) : analysis?.motifs.length ? (
                  <>
                    {analysis.motifs.slice(0, 8).map((motif, motifIndex) => (
                      <button className={`observation motif-observation ${selectedMotif === motifIndex ? 'selected-observation' : ''}`} key={`${motif.code}-${motif.actor}-${motif.targets.join('-')}`} onClick={() => {
                        setSelectedMotif(motifIndex)
                        setSelectedSquare(null)
                      }}>
                        <strong>{motif.code} · {motif.kind}</strong>
                        <span>{motif.explanation}</span>
                        <small>Участники: {[motif.actor, ...motif.targets].join(', ')} · уверенность {Math.round(motif.confidence * 100)}%</small>
                      </button>
                    ))}
                    {analysis.observations.filter((item) => item.category === 'THREAT' || item.category === 'DEFENSE').slice(0, 4).map((observation) => (
                      <button className={`observation observation-${observation.severity}`} key={`${observation.title}-${observation.message}`} onClick={() => setSelectedSquare(observation.subjects[0] ?? null)}>
                        <strong>{observation.title}</strong>
                        <span>{observation.message}</span>
                      </button>
                    ))}
                  </>
                ) : analysis?.observations.length ? (
                  analysis.observations.slice(0, 6).map((observation) => (
                    <button className={`observation observation-${observation.severity}`} key={`${observation.title}-${observation.message}`} onClick={() => setSelectedSquare(observation.subjects[0] ?? null)}>
                      <strong>{observation.title}</strong>
                      <span>{observation.message}</span>
                    </button>
                  ))
                ) : (
                  <p>Непосредственных уязвимостей не обнаружено.</p>
                )}
              </div>
            </aside>
          </section>

          <section className="controls">
            <button onClick={() => jump(0)} disabled={index === 0}>|◀</button>
            <button onClick={() => jump(index - 1)} disabled={index === 0}>◀</button>
            <button className="play" onClick={() => setPlaying((value) => !value)} disabled={index === game.timeline.length - 1}>
              {playing ? 'Пауза' : 'Старт'}
            </button>
            <button onClick={() => jump(index + 1)} disabled={index === game.timeline.length - 1}>▶</button>
            <button onClick={() => jump(game.timeline.length - 1)} disabled={index === game.timeline.length - 1}>▶|</button>
            <div className="progress"><span>{index} / {game.timeline.length - 1}</span><input type="range" min="0" max={game.timeline.length - 1} value={index} onChange={(event) => jump(Number(event.target.value))} /></div>
            <label>Режим<select value={mode} onChange={(event) => setMode(event.target.value as PlaybackMode)}><option value="fixed">Равномерно</option><option value="tempo" disabled={!tempoAvailable}>Темп партии</option></select></label>
            {mode === 'fixed' && <label>Интервал<input type="number" min="0.25" max="10" step="0.25" value={fixedSeconds} onChange={(event) => setFixedSeconds(Number(event.target.value))} /> с</label>}
            <label>Скорость<select value={speed} onChange={(event) => setSpeed(Number(event.target.value))}>{[0.25, 0.5, 1, 2, 4].map((value) => <option value={value} key={value}>{value}×</option>)}</select></label>
          </section>
          {game.warnings.map((warning) => <p className="warning" key={warning}>{warning}</p>)}
        </>
      )}
    </main>
  )
}