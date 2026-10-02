import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

import chess
import chess.pgn

from .models import (
    ExperienceEpisode,
    LearnedRule,
    MoveCandidate,
    RuleProposalResponse,
    SavedGameResponse,
    SavedGameSummary,
)
from .analysis import PIECE_VALUES, _best_capture_gain
from .personalities import get_personality
from .program import _candidate, choose_program_move
from .transition import analyze_move

RULES_VERSION = "0.1.0"
DEFAULT_DB = Path(__file__).parents[1] / "data" / "chess_vision.db"


def _db_path() -> Path:
    return Path(os.environ.get("CHESS_VISION_DB", DEFAULT_DB))


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(path)
    database.row_factory = sqlite3.Row
    try:
        yield database
        database.commit()
    finally:
        database.close()


def init_db() -> None:
    with connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                player_name TEXT NOT NULL,
                player_color TEXT NOT NULL,
                initial_fen TEXT NOT NULL,
                current_fen TEXT NOT NULL,
                result TEXT NOT NULL DEFAULT '*',
                status TEXT NOT NULL DEFAULT 'active',
                rules_version TEXT NOT NULL,
                personality_id TEXT NOT NULL DEFAULT 'universal',
                memory_processed INTEGER NOT NULL DEFAULT 0,
                active_plan TEXT,
                expected_reply_uci TEXT,
                continuation_uci TEXT
            );
            CREATE TABLE IF NOT EXISTS game_moves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL REFERENCES games(id),
                ply INTEGER NOT NULL,
                side TEXT NOT NULL,
                actor TEXT NOT NULL,
                uci TEXT NOT NULL,
                san TEXT NOT NULL,
                fen_before TEXT NOT NULL,
                fen_after TEXT NOT NULL,
                score INTEGER NOT NULL,
                reasons_json TEXT NOT NULL,
                alternatives_json TEXT NOT NULL,
                rules_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(game_id, ply)
            );
            CREATE TABLE IF NOT EXISTS experience_episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                personality_id TEXT NOT NULL,
                motif TEXT NOT NULL,
                context TEXT NOT NULL,
                decision TEXT NOT NULL,
                consequence TEXT NOT NULL,
                material_delta INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS learned_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                personality_id TEXT NOT NULL,
                pattern TEXT NOT NULL,
                response TEXT NOT NULL,
                weight REAL NOT NULL,
                confidence REAL NOT NULL,
                confirmations INTEGER NOT NULL DEFAULT 1,
                contradictions INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS rule_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                rule_json TEXT NOT NULL,
                baseline_version TEXT NOT NULL,
                backtest_result_json TEXT,
                approved_version TEXT
            );
            """
        )
        columns = {row["name"] for row in db.execute("PRAGMA table_info(games)").fetchall()}
        migrations = {
            "active_plan": "TEXT",
            "expected_reply_uci": "TEXT",
            "continuation_uci": "TEXT",
            "personality_id": "TEXT NOT NULL DEFAULT 'universal'",
            "memory_processed": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, definition in migrations.items():
            if name not in columns:
                db.execute(f"ALTER TABLE games ADD COLUMN {name} {definition}")


def create_game(player_name: str, player_color: str, personality_id: str = "universal") -> SavedGameResponse:
    if player_color != "white":
        raise ValueError("В текущей версии игрок играет белыми")
    get_personality(personality_id)
    now = datetime.now(UTC).isoformat()
    board = chess.Board()
    with connection() as db:
        cursor = db.execute(
            "INSERT INTO games(created_at, updated_at, player_name, player_color, initial_fen, current_fen, rules_version, personality_id) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (now, now, player_name, player_color, board.fen(), board.fen(), RULES_VERSION, personality_id),
        )
        game_id = cursor.lastrowid
    return SavedGameResponse(id=game_id, fen=board.fen(), pgn=_game_pgn(game_id), result="*", status="active", rules_version=RULES_VERSION, personality_id=personality_id)


def _row_game(game_id: int) -> sqlite3.Row:
    with connection() as db:
        row = db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    if row is None:
        raise ValueError(f"Партия {game_id} не найдена")
    return row


def _save_move(db: sqlite3.Connection, game_id: int, board: chess.Board, move: chess.Move, actor: str, candidate: MoveCandidate, alternatives: list[MoveCandidate]) -> None:
    fen_before = board.fen()
    side = "white" if board.turn == chess.WHITE else "black"
    ply = board.ply() + 1
    board.push(move)
    db.execute(
        "INSERT INTO game_moves(game_id, ply, side, actor, uci, san, fen_before, fen_after, score, reasons_json, alternatives_json, rules_version, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            game_id, ply, side, actor, candidate.uci, candidate.san, fen_before, board.fen(), candidate.score,
            json.dumps(candidate.reasons, ensure_ascii=False),
            json.dumps([item.model_dump() for item in alternatives], ensure_ascii=False),
            RULES_VERSION, datetime.now(UTC).isoformat(),
        ),
    )


def _process_game_memory(game_id: int) -> None:
    row = _row_game(game_id)
    if row["memory_processed"]:
        return
    with connection() as db:
        moves = db.execute(
            "SELECT * FROM game_moves WHERE game_id = ? AND actor = 'program' ORDER BY ply",
            (game_id,),
        ).fetchall()
    for move_row in moves:
        result = analyze_move(move_row["fen_before"], move_row["uci"])
        before_board = chess.Board(move_row["fen_before"])
        move = chess.Move.from_uci(move_row["uci"])
        after_board = before_board.copy(stack=False)
        after_board.push(move)
        mover = before_board.piece_at(move.from_square)
        moved_piece = after_board.piece_at(move.to_square)
        if mover and moved_piece and PIECE_VALUES[mover.piece_type] >= 3:
            loss = _best_capture_gain(after_board, move.to_square, after_board.turn)
            if loss >= 2:
                episode = record_experience(
                    row["personality_id"], "HANGING_PIECE", result.before.situation.context,
                    move_row["san"], f"фигура после хода потеряла материал {loss}", -loss,
                )
                learn_from_experience(episode)
        for change in result.changes:
            if change.impact != "negative":
                continue
            material_delta = -9 if "MATE" in change.category else -5 if "MATERIAL" in change.category else -3
            episode = record_experience(
                row["personality_id"], change.category, result.before.situation.context,
                move_row["san"], change.message, material_delta,
            )
            learn_from_experience(episode)
    with connection() as db:
        db.execute("UPDATE games SET memory_processed = 1 WHERE id = ?", (game_id,))


def _update_game(db: sqlite3.Connection, game_id: int, board: chess.Board) -> tuple[str, str]:
    result = board.result() if board.is_game_over() else "*"
    status = "finished" if board.is_game_over() else "active"
    db.execute(
        "UPDATE games SET updated_at = ?, current_fen = ?, result = ?, status = ? WHERE id = ?",
        (datetime.now(UTC).isoformat(), board.fen(), result, status, game_id),
    )
    return result, status


def play_saved_player_move(game_id: int, player_uci: str) -> SavedGameResponse:
    row = _row_game(game_id)
    if row["status"] != "active":
        raise ValueError("Партия уже завершена")
    board = chess.Board(row["current_fen"])
    if board.turn != chess.WHITE:
        raise ValueError("Сейчас очередь программы")
    player_move = chess.Move.from_uci(player_uci)
    if player_move not in board.legal_moves:
        raise ValueError(f"Ход {player_uci} нелегален")
    player_candidate = _candidate(board, player_move)
    with connection() as db:
        _save_move(db, game_id, board, player_move, "player", player_candidate, [])
        if row["expected_reply_uci"] and row["expected_reply_uci"] != player_uci:
            db.execute(
                "UPDATE games SET active_plan = NULL, expected_reply_uci = NULL, continuation_uci = NULL WHERE id = ?",
                (game_id,),
            )
        result, status = _update_game(db, game_id, board)
    return SavedGameResponse(
        id=game_id, fen=board.fen(), pgn=_game_pgn(game_id), result=result, status=status,
        rules_version=RULES_VERSION, personality_id=row["personality_id"], player_move=player_candidate,
    )


def play_saved_program_move(game_id: int) -> SavedGameResponse:
    row = _row_game(game_id)
    if row["status"] != "active":
        raise ValueError("Партия уже завершена")
    board = chess.Board(row["current_fen"])
    if board.turn != chess.BLACK:
        raise ValueError("Сейчас очередь игрока")
    remembered_continuation = row["continuation_uci"]
    personality = get_personality(row["personality_id"])
    learned = [rule.model_dump() for rule in list_learned_rules(row["personality_id"])]
    decision = choose_program_move(board.fen(), remembered_continuation, personality, learned)
    program_candidate = decision.move
    with connection() as db:
        if program_candidate:
            _save_move(db, game_id, board, chess.Move.from_uci(program_candidate.uci), "program", program_candidate, decision.alternatives)
            db.execute(
                "UPDATE games SET active_plan = ?, expected_reply_uci = ?, continuation_uci = ? WHERE id = ?",
                (program_candidate.plan, program_candidate.expected_reply_uci, program_candidate.continuation_uci, game_id),
            )
            result, status = _update_game(db, game_id, board)
        elif decision.resigned:
            result, status = decision.result or "1-0", "finished"
            db.execute(
                "UPDATE games SET updated_at = ?, result = ?, status = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), result, status, game_id),
            )
        else:
            result, status = _update_game(db, game_id, board)
    if status == "finished":
        _process_game_memory(game_id)
    return SavedGameResponse(
        id=game_id, fen=board.fen(), pgn=_game_pgn(game_id), result=result, status=status,
        rules_version=RULES_VERSION, personality_id=row["personality_id"], program_move=program_candidate,
        resignation_reason=decision.resignation_reason, utterance=decision.utterance, emotion=decision.emotion,
    )


def play_saved_turn(game_id: int, player_uci: str) -> SavedGameResponse:
    player_result = play_saved_player_move(game_id, player_uci)
    if player_result.status == "finished":
        return player_result
    program_result = play_saved_program_move(game_id)
    return program_result.model_copy(update={"player_move": player_result.player_move})


def list_games() -> list[SavedGameSummary]:
    with connection() as db:
        rows = db.execute(
            "SELECT g.*, COUNT(m.id) ply_count FROM games g LEFT JOIN game_moves m ON m.game_id = g.id GROUP BY g.id ORDER BY g.id DESC"
        ).fetchall()
    return [
        SavedGameSummary(
            id=row["id"], created_at=row["created_at"], updated_at=row["updated_at"], player_name=row["player_name"],
            player_color=row["player_color"], result=row["result"], status=row["status"], ply_count=row["ply_count"],
            rules_version=row["rules_version"], personality_id=row["personality_id"],
        )
        for row in rows
    ]


def _game_pgn(game_id: int) -> str:
    row = _row_game(game_id)
    game = chess.pgn.Game()
    game.headers["Event"] = "Chess Vision friendly game"
    game.headers["White"] = row["player_name"]
    game.headers["Black"] = get_personality(row["personality_id"]).name
    game.headers["Result"] = row["result"]
    game.headers["Personality"] = row["personality_id"]
    game.headers["RulesVersion"] = row["rules_version"]
    node = game
    with connection() as db:
        moves = db.execute("SELECT * FROM game_moves WHERE game_id = ? ORDER BY ply", (game_id,)).fetchall()
    for move_row in moves:
        node = node.add_variation(chess.Move.from_uci(move_row["uci"]))
        reasons = json.loads(move_row["reasons_json"])
        node.comment = f"{move_row['actor']}; score={move_row['score']}; " + "; ".join(reasons)
    return str(game)


def get_game(game_id: int) -> SavedGameResponse:
    row = _row_game(game_id)
    return SavedGameResponse(
        id=game_id, fen=row["current_fen"], pgn=_game_pgn(game_id), result=row["result"], status=row["status"], rules_version=row["rules_version"], personality_id=row["personality_id"]
    )


def record_experience(
    personality_id: str,
    motif: str,
    context: str,
    decision: str,
    consequence: str,
    material_delta: int,
) -> ExperienceEpisode:
    now = datetime.now(UTC).isoformat()
    with connection() as db:
        cursor = db.execute(
            "INSERT INTO experience_episodes(personality_id, motif, context, decision, consequence, material_delta, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (personality_id, motif, context, decision, consequence, material_delta, now),
        )
        episode_id = cursor.lastrowid
    return ExperienceEpisode(
        id=episode_id, personality_id=personality_id, motif=motif, context=context,
        decision=decision, consequence=consequence, material_delta=material_delta, created_at=now,
    )


def learn_from_experience(episode: ExperienceEpisode) -> LearnedRule | None:
    if episode.material_delta >= 0:
        return None
    pattern = f"{episode.motif}:{episode.context}"
    response = f"избегать решения {episode.decision}; прошлый результат {episode.material_delta}"
    with connection() as db:
        row = db.execute(
            "SELECT * FROM learned_rules WHERE personality_id = ? AND pattern = ? AND status = 'active'",
            (episode.personality_id, pattern),
        ).fetchone()
        if row:
            confirmations = row["confirmations"] + 1
            confidence = min(0.95, row["confidence"] + 0.1)
            db.execute(
                "UPDATE learned_rules SET confirmations = ?, confidence = ?, weight = ? WHERE id = ?",
                (confirmations, confidence, row["weight"] - 10, row["id"]),
            )
            rule_id = row["id"]
        else:
            cursor = db.execute(
                "INSERT INTO learned_rules(personality_id, pattern, response, weight, confidence) VALUES(?, ?, ?, -20, 0.55)",
                (episode.personality_id, pattern, response),
            )
            rule_id = cursor.lastrowid
    return get_learned_rule(rule_id)


def get_learned_rule(rule_id: int) -> LearnedRule:
    with connection() as db:
        row = db.execute("SELECT * FROM learned_rules WHERE id = ?", (rule_id,)).fetchone()
    if row is None:
        raise ValueError("Выученное правило не найдено")
    return LearnedRule(**dict(row))


def list_learned_rules(personality_id: str) -> list[LearnedRule]:
    with connection() as db:
        rows = db.execute(
            "SELECT * FROM learned_rules WHERE personality_id = ? AND status = 'active' ORDER BY confidence DESC, id DESC",
            (personality_id,),
        ).fetchall()
    return [LearnedRule(**dict(row)) for row in rows]


def create_rule_proposal(title: str, description: str, rule_json: dict) -> RuleProposalResponse:
    now = datetime.now(UTC).isoformat()
    with connection() as db:
        cursor = db.execute(
            "INSERT INTO rule_proposals(created_at, status, title, description, rule_json, baseline_version) VALUES(?, 'proposed', ?, ?, ?, ?)",
            (now, title, description, json.dumps(rule_json, ensure_ascii=False), RULES_VERSION),
        )
        proposal_id = cursor.lastrowid
    return get_rule_proposal(proposal_id)


def get_rule_proposal(proposal_id: int) -> RuleProposalResponse:
    with connection() as db:
        row = db.execute("SELECT * FROM rule_proposals WHERE id = ?", (proposal_id,)).fetchone()
    if row is None:
        raise ValueError("Предложение правила не найдено")
    return RuleProposalResponse(
        id=row["id"], created_at=row["created_at"], status=row["status"], title=row["title"], description=row["description"],
        rule_json=json.loads(row["rule_json"]), baseline_version=row["baseline_version"],
        backtest_result=json.loads(row["backtest_result_json"]) if row["backtest_result_json"] else None,
        approved_version=row["approved_version"],
    )


def list_rule_proposals() -> list[RuleProposalResponse]:
    with connection() as db:
        ids = [row["id"] for row in db.execute("SELECT id FROM rule_proposals ORDER BY id DESC").fetchall()]
    return [get_rule_proposal(proposal_id) for proposal_id in ids]


def backtest_rule_proposal(proposal_id: int) -> RuleProposalResponse:
    get_rule_proposal(proposal_id)
    games = list_games()
    result = {"games": len(games), "plies": sum(game.ply_count for game in games), "status": "requires_manual_review"}
    with connection() as db:
        db.execute(
            "UPDATE rule_proposals SET status = 'backtested', backtest_result_json = ? WHERE id = ?",
            (json.dumps(result), proposal_id),
        )
    return get_rule_proposal(proposal_id)


def approve_rule_proposal(proposal_id: int) -> RuleProposalResponse:
    proposal = get_rule_proposal(proposal_id)
    if proposal.status != "backtested":
        raise ValueError("Сначала требуется backtest")
    version = f"0.1.{proposal_id}"
    with connection() as db:
        db.execute(
            "UPDATE rule_proposals SET status = 'approved', approved_version = ? WHERE id = ?",
            (version, proposal_id),
        )
    return get_rule_proposal(proposal_id)
