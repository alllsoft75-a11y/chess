from __future__ import annotations

import json
import sys
import threading
from datetime import UTC, datetime

import chess
import chess.pgn

from .analysis import PIECE_VALUES, analyze_position
from .contexts import ContextLedger
from .models import TournamentGameResult, TournamentReport
from .personalities import list_personalities
from .program import choose_program_move
from .ratings import apply_game_result
from .storage import RULES_VERSION, connection

_THREADS: dict[int, threading.Thread] = {}


def _material(board: chess.Board, color: chess.Color) -> int:
    return sum(len(board.pieces(piece_type, color)) * value for piece_type, value in PIECE_VALUES.items() if piece_type != chess.KING)


def _technical_score(board: chess.Board) -> int:
    material = _material(board, chess.WHITE) - _material(board, chess.BLACK)
    analysis = analyze_position(board.fen())
    activity = sum(piece.activity.index for piece in analysis.pieces if piece.color == "white") - sum(
        piece.activity.index for piece in analysis.pieces if piece.color == "black"
    )
    critical = sum(1 for piece in analysis.pieces if piece.color == "black" and piece.state == "CRITICAL") - sum(
        1 for piece in analysis.pieces if piece.color == "white" and piece.state == "CRITICAL"
    )
    return material * 20 + activity // 10 + critical * 15


def _technical_result(score: int) -> str:
    if score >= 45:
        return "1-0"
    if score <= -45:
        return "0-1"
    return "1/2-1/2"


def play_personality_game(white, black, max_fullmoves: int) -> TournamentGameResult:
    board = chess.Board()
    game = chess.pgn.Game()
    game.headers["Event"] = "Chess Vision personality tournament"
    game.headers["White"] = white.name
    game.headers["Black"] = black.name
    node = game
    termination = "move_limit"
    result = "*"
    ledgers = {chess.WHITE: ContextLedger(), chess.BLACK: ContextLedger()}

    while not board.is_game_over() and board.fullmove_number <= max_fullmoves:
        side = board.turn
        personality = white if side == chess.WHITE else black
        ledger = ledgers[side]
        ledger.update(board)
        decision = choose_program_move(
            board.fen(), personality=personality, contexts=ledger.export(), quiet=True
        )
        if decision.resigned:
            result = decision.result or ("0-1" if side == chess.WHITE else "1-0")
            termination = "resignation"
            break
        if decision.move is None:
            result = board.result()
            termination = "rules"
            break
        move = chess.Move.from_uci(decision.move.uci)
        node = node.add_variation(move)
        node.comment = f"{personality.id}; plan={decision.move.plan}; " + "; ".join(decision.move.reasons[:4])
        board.push(move)
    else:
        result = board.result() if board.is_game_over() else "*"

    score = _technical_score(board)
    if result == "*":
        result = _technical_result(score)
        termination = "technical"
    elif termination == "move_limit":
        termination = "rules"
    game.headers["Result"] = result
    game.headers["Termination"] = termination
    return TournamentGameResult(
        white_id=white.id,
        black_id=black.id,
        result=result,
        termination=termination,
        fullmoves=board.fullmove_number - (1 if board.turn == chess.WHITE else 0),
        technical_score=score,
        pgn=str(game),
    )


def _pairings(players, games_per_pair: int):
    for first_index, first in enumerate(players):
        for second in players[first_index + 1 :]:
            pairings = [(first, second)]
            if games_per_pair == 2:
                pairings.append((second, first))
            for pairing in pairings:
                yield pairing


def _run_tournament(tournament_id: int, players, max_fullmoves: int, games_per_pair: int) -> None:
    try:
        for index, (white, black) in enumerate(_pairings(players, games_per_pair)):
            game = play_personality_game(white, black, max_fullmoves)
            rating = apply_game_result(white.id, black.id, game.result)
            with connection() as db:
                db.execute(
                    "INSERT INTO tournament_games(tournament_id, game_index, white_id, black_id, "
                    "white_rating_before, black_rating_before, white_rating_after, black_rating_after, "
                    "result, termination, fullmoves, technical_score, pgn) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        tournament_id, index, white.id, black.id,
                        rating["white_before"], rating["black_before"],
                        rating["white_after"], rating["black_after"],
                        game.result, game.termination, game.fullmoves, game.technical_score, game.pgn,
                    ),
                )
                db.execute(
                    "UPDATE tournaments SET played_games = played_games + 1 WHERE id = ?",
                    (tournament_id,),
                )
        with connection() as db:
            db.execute("UPDATE tournaments SET status = 'finished' WHERE id = ?", (tournament_id,))
    except Exception as error:  # pragma: no cover - защитный перехват фонового потока
        print(f"tournament {tournament_id} failed: {error}", file=sys.stderr)
        with connection() as db:
            db.execute(
                "UPDATE tournaments SET status = 'failed', error = ? WHERE id = ?",
                (str(error), tournament_id),
            )


def start_round_robin(max_fullmoves: int = 20, games_per_pair: int = 1, personality_ids: list[str] | None = None) -> int:
    if personality_ids:
        known = {profile.id: profile for profile in list_personalities()}
        missing = [pid for pid in personality_ids if pid not in known]
        if missing:
            raise ValueError(f"Неизвестные персонажи: {', '.join(missing)}")
        players = [known[pid] for pid in personality_ids]
    else:
        players = list_personalities()
    if len(players) < 2:
        raise ValueError("Для турнира нужно минимум два персонажа")
    pairs = len(players) * (len(players) - 1) // 2 * games_per_pair
    now = datetime.now(UTC).isoformat()
    with connection() as db:
        cursor = db.execute(
            "INSERT INTO tournaments(created_at, rules_version, max_fullmoves, games_per_pair, players_json, total_games) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (now, RULES_VERSION, max_fullmoves, games_per_pair, json.dumps([p.id for p in players]), pairs),
        )
        tournament_id = cursor.lastrowid
    thread = threading.Thread(
        target=_run_tournament,
        args=(tournament_id, players, max_fullmoves, games_per_pair),
        daemon=True,
        name=f"tournament-{tournament_id}",
    )
    _THREADS[tournament_id] = thread
    thread.start()
    return tournament_id


def _row_tournament_summary(row) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "rules_version": row["rules_version"],
        "max_fullmoves": row["max_fullmoves"],
        "games_per_pair": row["games_per_pair"],
        "players": json.loads(row["players_json"]),
        "status": row["status"],
        "error": row["error"],
        "total_games": row["total_games"],
        "played_games": row["played_games"],
    }


def get_tournament_summary(tournament_id: int) -> dict:
    with connection() as db:
        row = db.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,)).fetchone()
    if row is None:
        raise ValueError(f"Турнир {tournament_id} не найден")
    return _row_tournament_summary(row)


def list_tournaments() -> list[dict]:
    with connection() as db:
        rows = db.execute("SELECT * FROM tournaments ORDER BY id DESC").fetchall()
    return [_row_tournament_summary(row) for row in rows]


def get_tournament_report(tournament_id: int) -> dict:
    with connection() as db:
        row = db.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,)).fetchone()
        if row is None:
            raise ValueError(f"Турнир {tournament_id} не найден")
        games = db.execute(
            "SELECT * FROM tournament_games WHERE tournament_id = ? ORDER BY game_index", (tournament_id,)
        ).fetchall()
    summary = _row_tournament_summary(row)
    games_payload = [
        TournamentGameResult(
            white_id=game["white_id"],
            black_id=game["black_id"],
            result=game["result"],
            termination=game["termination"],
            fullmoves=game["fullmoves"],
            technical_score=game["technical_score"],
            pgn=game["pgn"],
        ).model_copy(update={
            "white_rating_before": round(game["white_rating_before"]),
            "black_rating_before": round(game["black_rating_before"]),
            "white_rating_after": round(game["white_rating_after"]),
            "black_rating_after": round(game["black_rating_after"]),
        })
        for game in games
    ]
    scores: dict[str, dict[str, float]] = {}
    for game in games:
        for side, points in (("white_id", 1.0 if game["result"] == "1-0" else 0.0 if game["result"] == "0-1" else 0.5),
                             ("black_id", 1.0 if game["result"] == "0-1" else 0.0 if game["result"] == "1-0" else 0.5)):
            pid = game[side]
            entry = scores.setdefault(pid, {"points": 0.0, "games": 0, "wins": 0, "draws": 0})
            entry["points"] += points
            entry["games"] += 1
            entry["wins"] += 1 if points == 1.0 else 0
            entry["draws"] += 1 if points == 0.5 else 0
    from .ratings import get_rating

    standings = []
    for pid in json.loads(row["players_json"]):
        from .personalities import get_personality

        profile = get_personality(pid)
        standings.append(profile.model_copy(update={"rating": get_rating(pid)}))
    standings.sort(key=lambda profile: (-scores.get(profile.id, {"points": 0})["points"], -profile.rating))
    return {**summary, "games": games_payload, "standings": standings, "scores": scores}


def run_round_robin(max_fullmoves: int = 20, games_per_pair: int = 1) -> TournamentReport:
    """Синхронный прогон без персистентности (совместимость со старыми вызовами/тестами)."""
    players = list_personalities()
    points = {profile.id: 0.0 for profile in players}
    games: list[TournamentGameResult] = []
    for white, black in _pairings(players, games_per_pair):
        game = play_personality_game(white, black, max_fullmoves)
        games.append(game)
        if game.result == "1-0":
            points[white.id] += 1
        elif game.result == "0-1":
            points[black.id] += 1
        else:
            points[white.id] += 0.5
            points[black.id] += 0.5
    standings = [profile.model_copy(update={"rating": int(points[profile.id] * 100)}) for profile in players]
    standings.sort(key=lambda profile: (-points[profile.id], profile.name))
    return TournamentReport(games=games, standings=standings)
