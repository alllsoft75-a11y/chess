import { useEffect, useMemo, useState } from 'react'
import { CharacterAvatar } from './CharacterAvatar'
import type { PersonalityProfile, RatingEntry, TournamentReport, TournamentSummary } from './types'

const STATUS_LABEL: Record<string, string> = {
  running: 'идёт',
  finished: 'завершён',
  failed: 'ошибка',
}

function errorDetail(payload: unknown, fallback: string): string {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) =>
          typeof item === 'object' && item !== null && 'msg' in item
            ? `${(item as { msg?: unknown }).msg}${'loc' in item ? ` (${(item as { loc?: unknown[] }).loc?.slice(-1)})` : ''}`
            : String(item)
        )
        .join('; ')
    }
  }
  return fallback
}

interface Props {
  onReview: (pgn: string) => void
}

export function TournamentPage({ onReview }: Props) {
  const [personalities, setPersonalities] = useState<PersonalityProfile[]>([])
  const [ratings, setRatings] = useState<RatingEntry[]>([])
  const [tournaments, setTournaments] = useState<TournamentSummary[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [detail, setDetail] = useState<TournamentReport | null>(null)
  const [maxFullmoves, setMaxFullmoves] = useState(12)
  const [gamesPerPair, setGamesPerPair] = useState(1)
  const [participants, setParticipants] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const refreshLists = () => {
    fetch('/api/v1/personalities').then((r) => r.json()).then(setPersonalities).catch(() => undefined)
    fetch('/api/v1/tournaments').then((r) => r.json()).then(setTournaments).catch(() => undefined)
    fetch('/api/v1/ratings').then((r) => r.json()).then(setRatings).catch(() => undefined)
  }

  useEffect(() => {
    refreshLists()
  }, [])

  const anyRunning = tournaments.some((t) => t.status === 'running') || detail?.status === 'running'

  useEffect(() => {
    if (!anyRunning) return
    const timer = window.setInterval(refreshLists, 3000)
    return () => window.clearInterval(timer)
  }, [anyRunning])

  const select = (id: number | null) => {
    setSelected(id)
    setDetail(null)
  }

  useEffect(() => {
    if (selected === null) return
    let cancelled = false
    const load = () => {
      fetch(`/api/v1/tournaments/${selected}`).then((r) => r.json()).then((payload) => {
        if (!cancelled) setDetail(payload)
      }).catch(() => undefined)
    }
    load()
    if (detail?.status !== 'running') return () => { cancelled = true }
    const timer = window.setInterval(load, 3000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [selected, detail?.status])

  const points = useMemo(() => {
    const table: Record<string, { points: number; games: number }> = {}
    if (!detail) return table
    for (const game of detail.games) {
      const white = table[game.white_id] ?? { points: 0, games: 0 }
      const black = table[game.black_id] ?? { points: 0, games: 0 }
      white.games += 1
      black.games += 1
      if (game.result === '1-0') white.points += 1
      else if (game.result === '0-1') black.points += 1
      else { white.points += 0.5; black.points += 0.5 }
      table[game.white_id] = white
      table[game.black_id] = black
    }
    return table
  }, [detail])

  async function start() {
    if (participants.length === 1) {
      setMessage('Выберите минимум двух участников или снимите все отметки (тогда играют все)')
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      const response = await fetch('/api/v1/tournaments/round-robin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          max_fullmoves: Math.min(60, Math.max(4, maxFullmoves)),
          games_per_pair: gamesPerPair,
          personality_ids: participants.length === personalities.length ? null : participants,
        }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(errorDetail(payload, 'Не удалось запустить турнир'))
      select(payload.id)
      refreshLists()
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="play-workspace">
      <aside className="play-panel tournament-panel">
        <div className="console-label">КОЛЬЦЕВОЙ ТУРНИР ПЕРСОНАЖЕЙ</div>
        <div className="tournament-setup">
          <label>Лимит ходов
            <input type="number" min={4} max={60} value={maxFullmoves} onChange={(e) => setMaxFullmoves(Number(e.target.value))} />
          </label>
          <label>Парий на пару
            <select value={gamesPerPair} onChange={(e) => setGamesPerPair(Number(e.target.value))}>
              <option value={1}>1 (белые у первого)</option>
              <option value={2}>2 (оба цвета)</option>
            </select>
          </label>
          <button disabled={busy} onClick={() => void start()}>Стартовать</button>
        </div>
        <p className="personality-description">Участники (пусто = все):</p>
        <div className="participant-grid">
          {personalities.map((p) => (
            <label key={p.id} className="participant">
              <input
                type="checkbox"
                checked={participants.includes(p.id)}
                onChange={(e) => setParticipants((items) => e.target.checked ? [...items, p.id] : items.filter((id) => id !== p.id))}
              />
              {p.name}
            </label>
          ))}
        </div>
        {message && <p className="warning">{message}</p>}
        <div className="console-label" style={{ marginTop: 14 }}>РЕЙТИНГ (ELO)</div>
        <table className="rating-table">
          <thead><tr><th>Персонаж</th><th>Elo</th><th>И</th><th>+/=/-</th></tr></thead>
          <tbody>
            {ratings.map((r) => (
              <tr key={r.personality_id}>
                <td>{r.name}</td>
                <td><b>{r.rating}</b></td>
                <td>{r.games}</td>
                <td>{r.wins}/{r.draws}/{r.losses}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </aside>
      <aside className="play-panel">
        <div className="console-label">ТУРНИРЫ</div>
        <div className="tournament-list">
          {tournaments.length === 0 && <p className="personality-description">Пока пусто — запустите первый турнир.</p>}
          {tournaments.map((t) => (
            <button
              key={t.id}
              className={`tournament-row ${selected === t.id ? 'selected-observation' : ''}`}
              onClick={() => select(t.id)}
            >
              <span>#{t.id} · {new Date(t.created_at).toLocaleString()}</span>
              <span>
                {STATUS_LABEL[t.status] ?? t.status}
                {t.status === 'running' && ` ${t.played_games}/${t.total_games}`}
                {t.status === 'failed' && t.error ? `: ${t.error}` : ''}
              </span>
            </button>
          ))}
        </div>
        {detail && (
          <div className="tournament-detail">
            <div className="console-label">ТАБЛИЦА #{detail.id}</div>
            <table className="rating-table">
              <thead><tr><th>#</th><th>Персонаж</th><th>Очки</th><th>Elo</th></tr></thead>
              <tbody>
                {detail.standings.map((p, index) => (
                  <tr key={p.id}>
                    <td>{index + 1}</td>
                    <td className="tournament-personality">
                      <CharacterAvatar personality={p} compact />
                      <span>{p.name} <small>({p.temperament})</small></span>
                    </td>
                    <td>{points[p.id] ? `${points[p.id].points} / ${points[p.id].games}` : '—'}</td>
                    <td><b>{p.rating}</b></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="console-label" style={{ marginTop: 12 }}>ПАРТИИ ({detail.games.length}/{detail.total_games})</div>
            <div className="tournament-games">
              {detail.games.map((g, index) => (
                <div key={index} className="tournament-game">
                  <span>{index + 1}. {g.white_id} — {g.black_id}</span>
                  <span>
                    <b>{g.result}</b>
                    {g.white_rating_after !== null && g.black_rating_after !== null && (
                      <small> ({Math.round(g.white_rating_after)} / {Math.round(g.black_rating_after)})</small>
                    )}
                    <small> · {g.termination} · {g.fullmoves} ход.</small>
                  </span>
                  <button onClick={() => onReview(g.pgn)}>разбор</button>
                </div>
              ))}
            </div>
          </div>
        )}
      </aside>
    </section>
  )
}
